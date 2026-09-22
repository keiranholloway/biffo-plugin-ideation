"""The founder-facing ASGI app (ADR-0021): endpoints + error mapping.

The gate (``require_founder``) and the service factory are overridden so the app is
exercised over an in-memory fake Core — the JWT verification and the SigV4 transport
are covered elsewhere (the SDK; the transport's own test).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ideation.adapter import CoreHttpError
from ideation.app import _derive_title, app, get_service, require_founder
from ideation.definitions import ANALYST_INSTRUCTIONS, CHALLENGER_AGENT_NAME
from ideation.effective_config import builtin_chat_agents
from ideation.manifest import MANIFEST_PATH
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


def _install_fake_cognito(
    monkeypatch: pytest.MonkeyPatch, *, groups: list[str], sub: str = "u1"
) -> None:
    """Point the *real* Cognito verifier `require_founder` calls at a fake, so a
    full HTTP request can exercise the gate for real without a network JWKS
    fetch or a signed JWT. Only the outbound signature-verification step is
    stubbed (``biffo_plugin_sdk._cognito.verify_cognito_jwt``) — the
    group-membership decision that actually allows/denies
    (``authorize()`` in ``biffo_plugin_sdk.user_serving``, called by the real
    ``require_founder`` dependency app.py builds at import time) is the real,
    unmodified code path.
    """
    monkeypatch.setenv("BIFFO_COGNITO_USER_POOL_ID", "pool-x")
    monkeypatch.setenv("BIFFO_COGNITO_REGION", "eu-west-1")
    monkeypatch.setenv("BIFFO_COGNITO_CLIENT_ID", "client-y")

    import biffo_plugin_sdk._cognito as cognito

    def fake_verify(token: str, **_: object) -> dict[str, object]:
        assert token  # the gate already rejects an empty token before calling this
        return {"sub": sub, "cognito:groups": groups}

    monkeypatch.setattr(cognito, "verify_cognito_jwt", fake_verify)


def test_admin_not_founder_is_admitted_by_the_apps_own_gate_end_to_end(
    core: FakeCore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for #163.

    PR #162 flipped the manifest's ``user_ingress.required_group`` from
    ``"founder"`` to ``"admin"`` (owner decision B on
    biffo-platform-app#70), but ``app.py`` kept its own, independent in-app
    re-check hardcoded to ``require_group("founder")`` — a second,
    hand-maintained copy of the same literal that PR #162 never touched. An
    admin-who-is-not-founder then passed the shared plugin host's
    manifest-driven ``group_gate`` and hit a 403 on every single route here
    anyway: the exact symptom #70 was filed to fix, still live end-to-end.

    This exercises the app's real, unmocked ``require_founder`` dependency
    (no dependency override — see ``_install_fake_cognito``) over a real HTTP
    request through the app's own route, not just the manifest fixture
    (``test_manifest.py``) and not a mocked-out ``require_founder`` override
    the way every other test in this file uses. The admitted group is read
    off the manifest itself, so this stays the actual cross-check between
    "what the manifest declares" and "what the app's gate accepts" even if
    the required group changes again.
    """
    manifest_group = json.loads(MANIFEST_PATH.read_text())["user_ingress"]["required_group"]
    assert manifest_group == "admin"  # the premise this test exists to guard

    app.dependency_overrides.clear()
    app.dependency_overrides[get_service] = lambda: IdeationService(core)
    _install_fake_cognito(monkeypatch, groups=[manifest_group], sub="admin-user")

    resp = TestClient(app).get("/sessions", headers={"Authorization": "Bearer admin-token"})

    assert resp.status_code == 200, resp.text
    app.dependency_overrides.clear()


def test_founder_without_admin_is_still_rejected_by_the_apps_own_gate_end_to_end(
    core: FakeCore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flip side of the regression above, against the same real gate: the
    manifest requires exactly ``"admin"``, not ``"admin" or "founder"``. A
    founder-only caller (the old, no-longer-sufficient group) must still be
    refused — proving the fix changed *which* group is required rather than
    just widening the check to admit everyone.
    """
    app.dependency_overrides.clear()
    app.dependency_overrides[get_service] = lambda: IdeationService(core)
    _install_fake_cognito(monkeypatch, groups=["founder"], sub="founder-user")

    resp = TestClient(app).get("/sessions", headers={"Authorization": "Bearer founder-token"})

    assert resp.status_code == 403, resp.text
    assert "admin" in resp.json()["detail"]
    app.dependency_overrides.clear()


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


# ---------------------------------------------------------------------------
# Issue #171 — the *other* enforcement point: Core's per-agent gate.
#
# #163/#170 fixed the per-surface gates (the plugin host's manifest `group_gate`
# and this app's own `require_founder`). Getting past both only buys a session.
# Every chat *turn* is separately authorised by Core, in
# `services/api/src/api/routers/internal_agent_chat.py`:
#
#     if agent.required_group not in founder.roles:
#         raise HTTPException(403, f"Access to this assistant requires the "
#                                  f"'{agent.required_group}' group.")
#
# `agent` there is the **stored chat-agent row** — the row this plugin seeds from
# `effective_config.builtin_chat_agents()` on every cold start, insert-if-absent
# and never overwritten. So the group named in that seed payload decides every
# chat turn for the life of the tenant, and a stale literal there 403s an
# admin-not-founder on their first real message even though every gate in this
# repo admitted them.
# ---------------------------------------------------------------------------


class _CoreWithPerAgentGate(FakeCore):
    """`FakeCore` plus Core's own per-agent authorisation gate, enforced against
    rows seeded from `builtin_chat_agents()`.

    Deliberately not a mock of the answer: the row is inserted by the same
    payload builder the real startup seeding posts, and the check is the same
    membership test `internal_agent_chat.py` runs. So the assertion is about the
    seed payload, not about a fixture someone hand-wrote to match it.
    """

    def __init__(self, *, caller_groups: list[str]) -> None:
        super().__init__()
        self.caller_groups = caller_groups
        self.agent_rows: dict[str, dict[str, Any]] = {}
        self.refusals: list[str] = []

    def seed(self, rows: list[dict[str, Any]]) -> None:
        """Core's seed route: insert-if-absent, never overwrite."""
        for row in rows:
            self.agent_rows.setdefault(row["agent_key"], dict(row))

    async def run_chat_turn(self, *, thread_id, owner_sub, agent_name, user_text) -> TurnResult:
        agent = self.agent_rows[agent_name]
        if agent["required_group"] not in self.caller_groups:
            detail = f"Access to this assistant requires the '{agent['required_group']}' group."
            self.refusals.append(detail)
            raise CoreHttpError(f"POST /internal/agent-chat/{agent_name} -> 403: {detail}")
        return await super().run_chat_turn(
            thread_id=thread_id, owner_sub=owner_sub, agent_name=agent_name, user_text=user_text
        )


def _gated_core_with_session(*, caller_groups: list[str], sub: str) -> _CoreWithPerAgentGate:
    core = _CoreWithPerAgentGate(caller_groups=caller_groups)
    core.seed(builtin_chat_agents())
    asyncio.run(
        core.create_session(
            owner_sub=sub,
            seed_idea="an app for coaches",
            thread_id="t1",
            challenger_agent_key=CHALLENGER_AGENT_NAME,
        )
    )
    return core


def test_admin_not_founder_can_take_an_actual_chat_turn_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #171 — the symptom #70 was filed to remove, at the gate
    #170 did not reach.

    An admin-who-is-not-founder passes the host's group gate and this app's own
    `require_founder` (both manifest-driven since #170) and can create a
    session — #170's own new test proves exactly that much. This goes one step
    further, to the thing the product actually is: sending a message. That call
    reaches Core's per-agent gate, which reads the seeded row's
    `required_group`, and while `builtin_chat_agents()` seeded `"founder"` this
    request 403'd on the first real turn.

    The admitted group is read off the manifest rather than named, so this stays
    a cross-check between what the manifest declares and what the seed payload
    demands even if the required group changes again.
    """
    manifest_group = json.loads(MANIFEST_PATH.read_text())["user_ingress"]["required_group"]
    core = _gated_core_with_session(caller_groups=[manifest_group], sub="admin-user")

    app.dependency_overrides.clear()
    app.dependency_overrides[get_service] = lambda: IdeationService(core)
    _install_fake_cognito(monkeypatch, groups=[manifest_group], sub="admin-user")

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/sessions/s1/messages",
        json={"message": "here is my answer"},
        headers={"Authorization": "Bearer admin-token"},
    )

    assert core.refusals == [], core.refusals
    assert resp.status_code == 200, resp.text
    assert resp.json()["reply"] == "challenge 1"
    assert resp.json()["turn_count"] == 1
    app.dependency_overrides.clear()


def test_a_chat_turn_is_refused_when_the_seeded_row_names_a_group_the_caller_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mirror case, against the same gate — without it the test above is
    vacuous, because a fake that never refuses anything passes it too.

    This seeds the pre-#171 row (`required_group: "founder"`) explicitly and
    sends the identical request: it must be refused, and the refusal must name
    the group the row demanded. That is the 403 an admin-not-founder was getting
    in production, reproduced here, and it is what the test above now proves the
    seed payload no longer asks for.
    """
    manifest_group = json.loads(MANIFEST_PATH.read_text())["user_ingress"]["required_group"]
    core = _CoreWithPerAgentGate(caller_groups=[manifest_group])
    core.seed([{**a, "required_group": "founder"} for a in builtin_chat_agents()])
    asyncio.run(
        core.create_session(
            owner_sub="admin-user",
            seed_idea="an app for coaches",
            thread_id="t1",
            challenger_agent_key=CHALLENGER_AGENT_NAME,
        )
    )

    app.dependency_overrides.clear()
    app.dependency_overrides[get_service] = lambda: IdeationService(core)
    _install_fake_cognito(monkeypatch, groups=[manifest_group], sub="admin-user")

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/sessions/s1/messages",
        json={"message": "here is my answer"},
        headers={"Authorization": "Bearer admin-token"},
    )

    assert resp.status_code != 200
    assert core.refusals == ["Access to this assistant requires the 'founder' group."]
    app.dependency_overrides.clear()
