"""The founder-facing Lambda app (ADR-0018): endpoints + error mapping.

The gate (``require_founder``) and the service factory are overridden so the app is
exercised over an in-memory fake Core — the JWT verification and the SigV4 transport
are covered elsewhere (the SDK; the transport's own test).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

from ideation.app import app, get_service, require_founder
from ideation.models import GATHERING, Run, Session, TurnResult
from ideation.service import IdeationService

_REPORT = {
    "prd": {
        "problem": "Coaches drown in admin.",
        "target_users": ["coaches"],
        "workflows": ["onboard"],
        "data_entities": ["client"],
        "capabilities": ["billing"],
        "out_of_scope": ["mobile"],
    },
    "scorecard": {
        "viability": {"score": 4, "rationale": "r"},
        "complexity": {"score": 3, "rationale": "r"},
        "economic_moat": {"score": 2, "rationale": "r"},
        "market_fit": {"score": 5, "rationale": "r"},
        "build_vs_buy": "build",
        "competitors": [],
        "summary": "Promising.",
    },
}


class FakeCore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.runs: dict[str, Run] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self._reply = 0

    async def create_session(self, *, owner_sub, seed_idea, thread_id) -> Session:
        self._seq += 1
        s = Session(
            id=f"s{self._seq}",
            owner_sub=owner_sub,
            seed_idea=seed_idea,
            status=GATHERING,
            thread_id=thread_id,
            turn_count=0,
        )
        self.sessions[s.id] = s
        return s

    async def get_session(self, *, owner_sub, session_id) -> Session | None:
        s = self.sessions.get(session_id)
        return s if s is not None and s.owner_sub == owner_sub else None

    async def set_turn_count(self, *, session_id, turn_count) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], turn_count=turn_count)

    async def set_status(self, *, session_id, status, analysis_run_id=None) -> None:
        cur = self.sessions[session_id]
        self.sessions[session_id] = replace(
            cur, status=status, analysis_run_id=analysis_run_id or cur.analysis_run_id
        )

    async def run_chat_turn(
        self, *, thread_id, owner_sub, agent_name, system_prompt, user_text, model
    ) -> TurnResult:
        self._reply += 1
        return TurnResult(reply=f"challenge {self._reply}", model=model)

    async def request_analysis(
        self, *, thread_id, owner_sub, agent_name, definition, output_tool
    ) -> str:
        self.runs["run-1"] = Run(id="run-1", status="running", messages=[])
        return "run-1"

    async def get_run(self, *, run_id) -> Run | None:
        return self.runs.get(run_id)

    async def save_report(self, *, session_id, prd, scorecard, model) -> None:
        self.reports[session_id] = {"prd": prd, "scorecard": scorecard, "model": model}

    async def get_report(self, *, session_id) -> dict[str, Any] | None:
        return self.reports.get(session_id)

    # test helper
    def complete_analysis(self, tool_call: dict[str, Any]) -> None:
        self.runs["run-1"] = Run(
            id="run-1",
            status="completed",
            messages=[{"role": "assistant", "tool_calls": [tool_call]}],
            model="analysis/m",
        )


def _tool_call() -> dict[str, Any]:
    import json

    return {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "submit_ideation_report",
            "arguments": json.dumps(_REPORT),
        },
    }


@pytest.fixture
def core() -> FakeCore:
    return FakeCore()


@pytest.fixture
def client(core: FakeCore) -> Iterator[TestClient]:
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub="alice", groups=["founder"], token="tok"
    )
    app.dependency_overrides[get_service] = lambda: IdeationService(
        core, chat_model="chat/m", analysis_model="analysis/m"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_start_session_creates_and_runs_the_first_turn(client):
    resp = client.post("/sessions", json={"seed_idea": "an app for coaches"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reply"] == "challenge 1"
    assert body["status"] == GATHERING
    assert body["turn_count"] == 1
    assert body["session_id"] == "s1"
    assert body["can_finalise"] is False  # min_turns not reached


def test_full_gathering_then_finalise_then_report(client, core):
    sid = client.post("/sessions", json={"seed_idea": "idea"}).json()["session_id"]
    # two more turns → 3 total (>= MIN_TURNS)
    client.post(f"/sessions/{sid}/messages", json={"message": "answer 1"})
    state = client.post(f"/sessions/{sid}/messages", json={"message": "answer 2"}).json()
    assert state["turn_count"] == 3
    assert state["can_finalise"] is True

    fin = client.post(f"/sessions/{sid}/finalise")
    assert fin.status_code == 202
    assert fin.json()["analysis_run_id"] == "run-1"

    # still analysing → report is null
    assert client.get(f"/sessions/{sid}/report").json()["report"] is None
    # the analyst run completes → the next poll materialises the report
    core.complete_analysis(_tool_call())
    report = client.get(f"/sessions/{sid}/report").json()
    assert report["status"] == "complete"
    assert report["report"]["prd"]["problem"] == "Coaches drown in admin."


def test_unknown_session_is_404(client):
    assert client.get("/sessions/nope").status_code == 404


def test_finalise_before_enough_turns_is_422(client):
    sid = client.post("/sessions", json={"seed_idea": "idea"}).json()["session_id"]
    assert client.post(f"/sessions/{sid}/finalise").status_code == 422  # < MIN_TURNS


def test_chat_after_finalise_is_409(client):
    sid = client.post("/sessions", json={"seed_idea": "idea"}).json()["session_id"]
    client.post(f"/sessions/{sid}/messages", json={"message": "a"})
    client.post(f"/sessions/{sid}/messages", json={"message": "b"})
    client.post(f"/sessions/{sid}/finalise")
    resp = client.post(f"/sessions/{sid}/messages", json={"message": "more"})
    assert resp.status_code == 409  # NotGatheringError


def test_the_app_is_gated_without_a_token(core):
    # No dependency overrides: require_founder runs for real. With no Authorization
    # header (and no Cognito env), the founder gate rejects the request.
    app.dependency_overrides.clear()
    monkeypatched = TestClient(app, raise_server_exceptions=False)
    resp = monkeypatched.post("/sessions", json={"seed_idea": "x"})
    assert resp.status_code == 401


def test_handler_strips_the_ingress_mount_prefix() -> None:
    # CloudFront forwards <base>/ideation/api/* unstripped; Mangum removes that
    # prefix so the routes above stay mounted at "/…" not "/ideation/api/…".
    from ideation.app import handler

    assert handler.config["api_gateway_base_path"] == "/ideation/api"
