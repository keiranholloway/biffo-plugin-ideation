"""source_candidate_id recording and the owner-scoped linked-content read."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast

import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

from ideation.adapter import CoreHttpGateway
from ideation.app import app, get_brainstorm_service, get_service, require_founder
from ideation.manifest import MANIFEST_PATH
from ideation.models import BS_QUALIFYING, COMPLETE, BrainstormSession, Session, TurnResult
from ideation.service import BrainstormService, IdeationService

_REPORT = {"prd": {"problem": "p"}, "scorecard": {"summary": "s"}, "model": "m"}


class FakeCore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.bs: dict[str, BrainstormSession] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.threads: dict[str, list[dict[str, Any]]] = {}
        self._seq = 0

    async def create_session(
        self,
        *,
        owner_sub,
        seed_idea,
        thread_id,
        challenger_agent_key,
        owner_email=None,
        source_candidate_id=None,
    ):
        self._seq += 1
        s = Session(
            id=f"s{self._seq}",
            owner_sub=owner_sub,
            seed_idea=seed_idea,
            status="gathering",
            thread_id=thread_id,
            turn_count=0,
            source_candidate_id=source_candidate_id,
        )
        self.sessions[s.id] = s
        return s

    async def get_session(self, *, owner_sub, session_id):
        s = self.sessions.get(session_id)
        return s if s and s.owner_sub == owner_sub else None

    async def list_sessions(self, *, owner_sub):
        return [s for s in self.sessions.values() if s.owner_sub == owner_sub]

    async def set_turn_count(self, *, session_id, turn_count):
        self.sessions[session_id] = replace(self.sessions[session_id], turn_count=turn_count)

    async def get_report(self, *, session_id):
        return self.reports.get(session_id)

    async def get_thread_messages(self, *, thread_id):
        return self.threads.get(thread_id, [])

    async def create_brainstorm_session(
        self, *, owner_sub, target, geography, problem, thread_id, title=None,
        owner_email=None, source_candidate_id=None,
    ):  # fmt: skip
        self._seq += 1
        b = BrainstormSession(
            id=f"b{self._seq}",
            owner_sub=owner_sub,
            status=BS_QUALIFYING,
            thread_id=thread_id,
            research_findings=[{"angle": "market", "status": "succeeded", "findings": []}],
            source_candidate_id=source_candidate_id,
        )
        self.bs[b.id] = b
        return b

    async def get_brainstorm_session(self, *, owner_sub, session_id):
        b = self.bs.get(session_id)
        return b if b and b.owner_sub == owner_sub else None

    async def list_brainstorm_sessions(self, *, owner_sub):
        return [b for b in self.bs.values() if b.owner_sub == owner_sub]

    async def list_brainstorm_opportunities(self, *, owner_sub, session_id):
        return []


@pytest.fixture
def core() -> FakeCore:
    return FakeCore()


@pytest.fixture
def as_user(core: FakeCore) -> Iterator[Any]:
    current = {"sub": "alice"}
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub=current["sub"], groups=["admin"], token="tok"
    )
    app.dependency_overrides[get_service] = lambda: IdeationService(cast(Any, core))
    app.dependency_overrides[get_brainstorm_service] = lambda: BrainstormService(cast(Any, core))
    client = TestClient(app)

    def switch(sub: str) -> TestClient:
        current["sub"] = sub
        return client

    yield switch
    app.dependency_overrides.clear()


def _run(coro):
    return asyncio.run(coro)


async def _link(core: FakeCore, owner: str, candidate: str | None) -> Session:
    s = await IdeationService(cast(Any, core)).start_session(
        owner_sub=owner, seed_idea="idea", source_candidate_id=candidate
    )
    core.sessions[s.id] = replace(s, status=COMPLETE)
    core.reports[s.id] = _REPORT
    core.threads[s.thread_id] = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "challenge"},
    ]
    return core.sessions[s.id]


def test_same_owner_gets_linked_report_transcript_and_research(core, as_user):
    _run(_link(core, "alice", "cand-1"))
    _run(
        BrainstormService(cast(Any, core)).start_session(
            owner_sub="alice", problem="x", source_candidate_id="cand-1"
        )
    )
    resp = as_user("alice").get("/linked/cand-1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reports"][0]["report"] == _REPORT
    assert [m["role"] for m in body["reports"][0]["transcript"]] == ["user", "assistant"]
    assert body["research"][0]["research"][0]["angle"] == "market"


def test_different_owner_gets_404(core, as_user):
    _run(_link(core, "alice", "cand-1"))
    assert as_user("mallory").get("/linked/cand-1").status_code == 404


def test_sessions_without_candidate_id_are_not_returned(core, as_user):
    _run(_link(core, "alice", None))
    _run(_link(core, "alice", "other"))
    assert as_user("alice").get("/linked/cand-1").status_code == 404
    assert as_user("alice").get("/linked/").status_code in (404, 405)


def test_start_session_records_source_candidate_id(core, as_user):
    async def run_chat_turn(**_):
        return TurnResult(reply="r")

    core.run_chat_turn = run_chat_turn  # type: ignore[attr-defined]
    resp = as_user("alice").post("/sessions", json={"seed_idea": "i", "source_candidate_id": "c9"})
    assert resp.status_code == 201, resp.text
    assert next(iter(core.sessions.values())).source_candidate_id == "c9"


def test_adapter_writes_and_reads_source_candidate_id():
    _run(_adapter_case())


async def _adapter_case():
    sent: list[dict[str, Any]] = []

    class T:
        async def request(self, method, path, *, json=None, params=None):
            assert json is not None
            sent.append(json)
            return {
                "id": "1", "owner_sub": "a", "seed_idea": "i", "status": "gathering",
                "thread_id": "t", **json,
            }  # fmt: skip

    s = await CoreHttpGateway(T()).create_session(
        owner_sub="a", seed_idea="i", thread_id="t", challenger_agent_key="k",
        source_candidate_id="c1",
    )  # fmt: skip
    assert sent[0]["source_candidate_id"] == "c1"
    assert s.source_candidate_id == "c1"


def test_manifest_declares_column_and_idea_scout_grant():
    m = json.loads(MANIFEST_PATH.read_text())
    tables = {t["name"]: t for t in m["tables"]}
    for name in ("ideation_sessions", "ideation_reports", "brainstorm_sessions"):
        assert "system:idea-scout" in tables[name]["owner_scoped_service"]["allowed_principals"]
        assert "system:ideation" in tables[name]["owner_scoped_service"]["allowed_principals"]
    cols = {c["name"]: c for c in tables["ideation_sessions"]["columns"]}
    assert cols["source_candidate_id"]["nullable"] is True
