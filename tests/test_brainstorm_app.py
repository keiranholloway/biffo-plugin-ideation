"""API-level tests: a Brain-Storming session is started and driven through a
capped qualifying conversation via the new routes, over an in-memory fake Core."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast

import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

from ideation.app import app, get_brainstorm_service, require_founder
from ideation.brainstorm_definitions import (
    QUALIFIER_AGENT_NAME,
    QUALIFIER_INSTRUCTIONS,
    QUALIFIER_MAX_TURNS,
)
from ideation.models import BS_QUALIFYING, BrainstormSession, TurnResult
from ideation.service import BrainstormService


class FakeCore:
    def __init__(self) -> None:
        self.sessions: dict[str, BrainstormSession] = {}
        self.turns: list[dict[str, Any]] = []
        self._seq = 0

    async def create_brainstorm_session(
        self, *, owner_sub, target, geography, problem, thread_id, title=None
    ):
        self._seq += 1
        s = BrainstormSession(
            id=f"b{self._seq}",
            owner_sub=owner_sub,
            status=BS_QUALIFYING,
            title=title,
            target=target,
            geography=geography,
            problem=problem,
            thread_id=thread_id,
            created_at=f"2026-01-01T00:00:0{self._seq}",
        )
        self.sessions[s.id] = s
        return s

    async def get_brainstorm_session(self, *, owner_sub, session_id):
        s = self.sessions.get(session_id)
        return s if s is not None and s.owner_sub == owner_sub else None

    async def list_brainstorm_sessions(self, *, owner_sub):
        return [s for s in self.sessions.values() if s.owner_sub == owner_sub]

    async def update_brainstorm_session(self, *, session_id, **fields):
        self.sessions[session_id] = replace(self.sessions[session_id], **fields)

    async def delete_brainstorm_session(self, *, session_id):
        self.sessions[session_id] = replace(self.sessions[session_id], deleted=True)

    async def run_chat_turn(self, *, thread_id, owner_sub, agent_name, user_text):
        self.turns.append({"thread_id": thread_id, "agent_name": agent_name, "text": user_text})
        return TurnResult(reply=f"question {len(self.turns)}")


@pytest.fixture
def core() -> FakeCore:
    return FakeCore()


@pytest.fixture
def client(core: FakeCore) -> Iterator[TestClient]:
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub="alice", groups=["founder"], token="tok"
    )
    app.dependency_overrides[get_brainstorm_service] = lambda: BrainstormService(cast(Any, core))
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_start_session_runs_the_opening_qualifier_turn(client, core):
    resp = client.post("/brainstorm/sessions", json={"target": "dentists", "geography": "UK"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reply"] == "question 1"
    assert body["status"] == BS_QUALIFYING
    assert body["turn_count"] == 1
    assert body["max_turns"] == QUALIFIER_MAX_TURNS
    assert body["target"] == "dentists"
    assert core.turns[0]["agent_name"] == QUALIFIER_AGENT_NAME
    assert "dentists" in core.turns[0]["text"] and "UK" in core.turns[0]["text"]


def test_start_requires_some_input(client):
    assert client.post("/brainstorm/sessions", json={}).status_code == 422
    assert client.post("/brainstorm/sessions", json={"target": "  "}).status_code == 422


def test_capped_qualifying_conversation(client, core):
    sid = client.post("/brainstorm/sessions", json={"problem": "admin"}).json()["session_id"]
    for expected in range(2, QUALIFIER_MAX_TURNS + 1):
        r = client.post(f"/brainstorm/sessions/{sid}/messages", json={"message": "answer"})
        assert r.status_code == 200, r.text
        assert r.json()["turn_count"] == expected
        assert r.json()["reply"] == f"question {expected}"
    # all turns share the session's one thread
    assert len({t["thread_id"] for t in core.turns}) == 1

    over = client.post(f"/brainstorm/sessions/{sid}/messages", json={"message": "more"})
    assert over.status_code == 409
    assert len(core.turns) == QUALIFIER_MAX_TURNS  # the capped turn never reached the agent


def test_get_list_delete(client):
    a = client.post("/brainstorm/sessions", json={"target": "a"}).json()["session_id"]
    b = client.post("/brainstorm/sessions", json={"target": "b"}).json()["session_id"]
    assert client.get(f"/brainstorm/sessions/{a}").json()["target"] == "a"
    assert [s["session_id"] for s in client.get("/brainstorm/sessions").json()] == [b, a]

    assert client.post(f"/brainstorm/sessions/{a}/delete").status_code == 204
    assert client.get(f"/brainstorm/sessions/{a}").status_code == 404
    assert [s["session_id"] for s in client.get("/brainstorm/sessions").json()] == [b]
    assert (
        client.post(f"/brainstorm/sessions/{a}/messages", json={"message": "x"}).status_code == 404
    )


def test_unknown_and_foreign_sessions_are_404(client, core):
    sid = client.post("/brainstorm/sessions", json={"target": "a"}).json()["session_id"]
    core.sessions[sid] = replace(core.sessions[sid], owner_sub="bob")
    assert client.get(f"/brainstorm/sessions/{sid}").status_code == 404
    assert client.get("/brainstorm/sessions/nope").status_code == 404


def test_no_research_launch_route(client):
    sid = client.post("/brainstorm/sessions", json={"target": "a"}).json()["session_id"]
    assert client.post(f"/brainstorm/sessions/{sid}/research").status_code in (404, 405)


def test_qualifier_prompt_is_blue_sky_not_pressure_testing():
    assert "STEP ONE OF TWO" in QUALIFIER_INSTRUCTIONS
    assert "do NOT pressure-test" in QUALIFIER_INSTRUCTIONS


def test_opportunities_route_is_empty_for_a_fresh_session(client, core):
    sid = client.post("/brainstorm/sessions", json={"target": "dentists"}).json()["session_id"]

    async def _none(*, owner_sub, session_id):
        return []

    core.list_brainstorm_opportunities = _none  # type: ignore[attr-defined]
    resp = client.get(f"/brainstorm/sessions/{sid}/opportunities")
    assert resp.status_code == 200
    assert resp.json() == {"opportunities": []}


def test_opportunities_route_404s_for_unknown_session(client):
    assert client.get("/brainstorm/sessions/nope/opportunities").status_code == 404
