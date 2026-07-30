"""The founder-facing ASGI app (ADR-0021): endpoints + error mapping.

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
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ideation.app import _derive_title, app, get_service, require_founder
from ideation.definitions import ANALYST_INSTRUCTIONS
from ideation.models import GATHERING, Run, Session, TurnResult
from ideation.service import IdeationService

#: What Core reports a challenger turn ran on. Resolved from the stored
#: chat-agent row, server-side; nothing in this plugin selects it.
CORE_RESOLVED_MODEL = "core-resolved/challenger"

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
        self._submitted_idea: str | None = None
        self._own_config: dict[str, dict[str, Any]] = {}
        self._active_agents: dict[str, list[dict[str, Any]]] = {}

    async def create_session(
        self, *, owner_sub, seed_idea, thread_id, challenger_agent_key
    ) -> Session:
        self._seq += 1
        s = Session(
            id=f"s{self._seq}",
            owner_sub=owner_sub,
            seed_idea=seed_idea,
            status=GATHERING,
            thread_id=thread_id,
            turn_count=0,
            challenger_agent_key=challenger_agent_key,
        )
        self.sessions[s.id] = s
        return s

    async def get_session(self, *, owner_sub, session_id) -> Session | None:
        s = self.sessions.get(session_id)
        return s if s is not None and s.owner_sub == owner_sub else None

    async def list_sessions(self, *, owner_sub) -> list[Session]:
        return [s for s in self.sessions.values() if s.owner_sub == owner_sub]

    async def set_turn_count(self, *, session_id, turn_count) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], turn_count=turn_count)

    async def set_status(self, *, session_id, status, analysis_run_id=None) -> None:
        cur = self.sessions[session_id]
        self.sessions[session_id] = replace(
            cur, status=status, analysis_run_id=analysis_run_id or cur.analysis_run_id
        )

    async def delete_session(self, *, session_id) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], deleted=True)

    async def run_chat_turn(self, *, thread_id, owner_sub, agent_name, user_text) -> TurnResult:
        self._reply += 1
        # The model on the result is the one *Core* resolved from the agent's
        # registration and reports back — not one this side chose. The fake used
        # to echo the caller's own `model` argument, which made a discarded
        # parameter look like it round-tripped (issue #68).
        return TurnResult(reply=f"challenge {self._reply}", model=CORE_RESOLVED_MODEL)

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

    async def get_submitted_idea(self, *, owner_sub) -> str | None:
        return getattr(self, "_submitted_idea", None)

    async def get_own_config(self, *, role) -> dict[str, Any] | None:
        return self._own_config.get(role)

    async def seed_own_config(self, *, config: list[dict[str, Any]]) -> list[dict[str, bool]]:
        """Insert-if-absent, matching Core's real seed-route contract. Only
        present so this fake satisfies ``CoreGateway`` structurally — the app
        layer's own startup seeding is exercised in
        ``tests/test_startup_seeding.py``, not through this fake."""
        result = []
        for row in config:
            role = row["role"]
            created = role not in self._own_config
            if created:
                self._own_config[role] = {
                    "system_prompt": row["system_prompt"],
                    "model": row["model"],
                }
            result.append({"role": role, "created": created})
        return result

    async def list_active_agents(self, *, role) -> list[dict[str, Any]]:
        return self._active_agents.get(role, [])

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
    core = FakeCore()
    # Seed the analyst config, matching what startup seeding guarantees in the
    # real app (issue #93) — finalise() has no fallback of its own any more, so
    # a test exercising anything other than the missing-row case needs a row
    # to exist, exactly like a real deployment does after cold start.
    core._own_config["analyst"] = {"system_prompt": ANALYST_INSTRUCTIONS, "model": "analysis/m"}
    return core


@pytest.fixture
def client(core: FakeCore) -> Iterator[TestClient]:
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub="alice", groups=["founder"], token="tok"
    )
    app.dependency_overrides[get_service] = lambda: IdeationService(core)
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


def test_start_session_forwards_the_chosen_challenger_agent_key(client, core):
    core._active_agents["challenger"] = [{"agent_key": "custom", "agent_name": "Custom"}]
    resp = client.post("/sessions", json={"seed_idea": "an idea", "challenger_agent_key": "custom"})
    assert resp.status_code == 201, resp.text
    sid = resp.json()["session_id"]
    assert core.sessions[sid].challenger_agent_key == "custom"


def test_start_session_without_a_chosen_agent_falls_back_to_the_default(client, core):
    resp = client.post("/sessions", json={"seed_idea": "an idea"})
    assert resp.status_code == 201, resp.text
    sid = resp.json()["session_id"]
    from ideation.definitions import CHALLENGER_AGENT_NAME

    assert core.sessions[sid].challenger_agent_key == CHALLENGER_AGENT_NAME


def test_list_agents_returns_only_key_and_name(client, core):
    core._active_agents["challenger"] = [
        {
            "agent_key": "skeptic",
            "agent_name": "The Skeptic",
            "system_prompt": "top secret prompt text",
            "model": "some/model",
        }
    ]
    resp = client.get("/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"agent_key": "skeptic", "agent_name": "The Skeptic"}]
    assert "system_prompt" not in body[0]
    assert "model" not in body[0]


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


def test_finalise_without_a_seeded_analyst_row_is_502_and_names_the_role(client, core):
    """Issue #93: with no analyst row (seeding failed or never ran), finalise()
    must fail loudly and name the missing role — not silently read
    ``ANALYST_INSTRUCTIONS``. The ``core`` fixture normally seeds this row
    (matching what real startup seeding guarantees); this test removes it to
    exercise the one case that guarantee is meant to prevent."""
    core._own_config.pop("analyst", None)
    sid = client.post("/sessions", json={"seed_idea": "idea"}).json()["session_id"]
    client.post(f"/sessions/{sid}/messages", json={"message": "a"})
    client.post(f"/sessions/{sid}/messages", json={"message": "b"})

    resp = client.post(f"/sessions/{sid}/finalise")

    assert resp.status_code == 502
    assert "analyst" in resp.json()["detail"]


def test_the_app_is_gated_without_a_token(core):
    # No dependency overrides: require_founder runs for real. With no Authorization
    # header (and no Cognito env), the founder gate rejects the request.
    app.dependency_overrides.clear()
    monkeypatched = TestClient(app, raise_server_exceptions=False)
    resp = monkeypatched.post("/sessions", json={"seed_idea": "x"})
    assert resp.status_code == 401


def test_exposes_an_asgi_app_not_a_lambda_handler() -> None:
    # Under ADR-0021 the shared plugin host provides the Lambda entrypoint and
    # mounts this app at /api/v1/plugins/ideation, stripping that prefix — so the
    # module exposes the FastAPI `app` (what user_ingress.app references) and no
    # longer ships its own Mangum handler.
    import ideation.app as app_module

    assert isinstance(app_module.app, FastAPI)
    assert not hasattr(app_module, "handler")


class TestDeriveTitle:
    def test_short_string_unchanged(self):
        result = _derive_title("build a coaching app")
        assert result == "build a coaching app"

    def test_long_string_truncated_at_word_boundary(self):
        long_idea = (
            "I want to build an app that helps coaches manage their admin tasks and scheduling"
        )
        result = _derive_title(long_idea, max_len=60)
        assert result.endswith("…")
        assert len(result) <= 62  # max_len + len("…")
        assert not result.endswith(" …")  # No trailing space before ellipsis

    def test_long_string_with_no_space_within_max_len_hard_truncates(self):
        # A pathological case: a single very long word
        long_word = "x" * 80
        result = _derive_title(long_word, max_len=60)
        assert result == "x" * 60 + "…"

    def test_leading_and_trailing_whitespace_stripped(self):
        idea = "   idea with spaces   "
        result = _derive_title(idea, max_len=100)
        assert result == "idea with spaces"


def test_list_sessions_empty_when_no_sessions(client):
    resp = client.get("/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sessions_returns_summaries_in_service_order(client, core):
    # Create two sessions for alice
    s1_id = client.post("/sessions", json={"seed_idea": "first idea"}).json()["session_id"]
    s2_id = client.post("/sessions", json={"seed_idea": "second idea"}).json()["session_id"]

    resp = client.get("/sessions")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 2
    # They should come in the order the service returns them
    assert summaries[0]["session_id"] == s1_id
    assert summaries[1]["session_id"] == s2_id


def test_list_sessions_uses_explicit_title_when_set(client, core):
    seed = "an idea"
    sid = client.post("/sessions", json={"seed_idea": seed}).json()["session_id"]
    # Manually set a title on the session
    core.sessions[sid] = replace(core.sessions[sid], title="Explicit Title")

    resp = client.get("/sessions")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 1
    assert summaries[0]["title"] == "Explicit Title"


def test_list_sessions_derives_title_from_seed_idea_when_not_set(client, core):
    # Use a seed_idea longer than 60 chars to exercise truncation
    long_seed = "I want to build an app that helps coaches manage their admin and scheduling"
    client.post("/sessions", json={"seed_idea": long_seed})

    resp = client.get("/sessions")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 1
    summary = summaries[0]
    # Title should be derived from seed_idea and truncated
    assert summary["title"].endswith("…")
    assert summary["title"] != long_seed  # Should be truncated
    assert len(summary["title"]) < len(long_seed)


def test_list_sessions_includes_status_and_created_at(client, core):
    sid = client.post("/sessions", json={"seed_idea": "test idea"}).json()["session_id"]
    # Set created_at on the session
    core.sessions[sid] = replace(core.sessions[sid], created_at="2026-07-25T10:00:00Z")

    resp = client.get("/sessions")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 1
    summary = summaries[0]
    assert "status" in summary
    assert summary["status"] == GATHERING
    assert "created_at" in summary
    assert summary["created_at"] == "2026-07-25T10:00:00Z"


def test_list_sessions_response_shape(client):
    """Verify the response has exactly the expected keys."""
    client.post("/sessions", json={"seed_idea": "test"})

    resp = client.get("/sessions")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 1
    summary = summaries[0]
    # Should have exactly these keys: session_id, title, status, created_at
    assert set(summary.keys()) == {"session_id", "title", "status", "created_at"}


def test_get_submitted_idea_returns_the_idea(client, core):
    core._submitted_idea = "build a coaching app"

    resp = client.get("/submitted-idea")

    assert resp.status_code == 200
    assert resp.json() == {"idea": "build a coaching app"}


def test_get_submitted_idea_returns_null_when_not_submitted(client, core):
    resp = client.get("/submitted-idea")

    assert resp.status_code == 200
    assert resp.json() == {"idea": None}


def test_delete_session_returns_204(client, core):
    sid = client.post("/sessions", json={"seed_idea": "an idea"}).json()["session_id"]
    resp = client.post(f"/sessions/{sid}/delete")
    assert resp.status_code == 204

    # Verify session is marked as deleted
    assert core.sessions[sid].deleted is True


def test_delete_nonexistent_session_is_404(client):
    resp = client.post("/sessions/nope/delete")
    assert resp.status_code == 404


def test_delete_another_founders_session_is_404(client, core):
    # Create a session owned by alice
    sid = client.post("/sessions", json={"seed_idea": "alice's idea"}).json()["session_id"]

    # Try to delete it as a different founder (bob)
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub="bob", groups=["founder"], token="tok"
    )
    resp = client.post(f"/sessions/{sid}/delete")
    assert resp.status_code == 404

    # Restore the override
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub="alice", groups=["founder"], token="tok"
    )


def test_read_report_returns_explicit_title_when_set(client, core):
    """read_report returns the explicit title when Session.title is set."""
    seed = "an idea"
    sid = client.post("/sessions", json={"seed_idea": seed}).json()["session_id"]
    # Manually set a title on the session
    core.sessions[sid] = replace(core.sessions[sid], title="Explicit Title")
    # Set the session to complete status and add a report
    core.complete_analysis(_tool_call())
    core.sessions[sid] = replace(core.sessions[sid], status="complete")
    # Save the report so it's available
    core.reports[sid] = _REPORT

    resp = client.get(f"/sessions/{sid}/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Explicit Title"
    assert body["report"] is not None


def test_read_report_returns_derived_title_when_not_set(client, core):
    """read_report returns the derived title when Session.title is None."""
    # Use a seed_idea longer than 60 chars to exercise truncation
    long_seed = "I want to build an app that helps coaches manage their admin and scheduling"
    sid = client.post("/sessions", json={"seed_idea": long_seed}).json()["session_id"]
    # Ensure title is None
    core.sessions[sid] = replace(core.sessions[sid], title=None)
    # Set the session to complete status and add a report
    core.complete_analysis(_tool_call())
    core.sessions[sid] = replace(core.sessions[sid], status="complete")
    # Save the report so it's available
    core.reports[sid] = _REPORT

    resp = client.get(f"/sessions/{sid}/report")
    assert resp.status_code == 200
    body = resp.json()
    # Title should be derived from seed_idea and truncated
    assert body["title"].endswith("…")
    assert body["title"] != long_seed  # Should be truncated
    assert len(body["title"]) < len(long_seed)
    assert body["report"] is not None


def test_read_report_title_matches_list_sessions_title_anti_drift(client, core):
    """For the same session, title from GET /sessions/{id}/report equals title from GET /sessions.

    This is the anti-drift test that justifies the whole design — using one session
    fixture and both routes to ensure the two can never disagree about what an idea
    is called.
    """
    # Create a session with a long seed idea
    long_seed = "I want to build an app that helps coaches manage their admin and scheduling"
    sid = client.post("/sessions", json={"seed_idea": long_seed}).json()["session_id"]

    # Get the title from the sessions list
    list_resp = client.get("/sessions")
    assert list_resp.status_code == 200
    list_summaries = list_resp.json()
    assert len(list_summaries) == 1
    list_title = list_summaries[0]["title"]

    # Now complete the analysis and get the report title
    core.complete_analysis(_tool_call())
    core.sessions[sid] = replace(core.sessions[sid], status="complete")
    # Save the report so it's available
    core.reports[sid] = _REPORT

    report_resp = client.get(f"/sessions/{sid}/report")
    assert report_resp.status_code == 200
    report_body = report_resp.json()
    report_title = report_body["title"]

    # The titles must be exactly equal
    assert report_title == list_title
