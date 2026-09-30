"""Research fan-out, synthesis and the state machine, against a fake Core."""

from __future__ import annotations

import asyncio
import functools
import json
from dataclasses import replace
from typing import Any, cast

import pytest

from ideation.brainstorm_definitions import (
    OPPORTUNITIES_TOOL_NAME,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    brainstorm_seed_payloads,
    research_definition,
)
from ideation.models import (
    BS_COMPLETE,
    BS_FAILED,
    BS_QUALIFYING,
    BS_RESEARCHING,
    BS_SYNTHESISING,
    AgentRunView,
    BrainstormSession,
)
from ideation.service import (
    AgentConfigMissingError,
    BrainstormService,
    NotGatheringError,
)


def _sync(fn):
    """Run an async test body to completion (no pytest-asyncio here — the rest
    of the suite uses ``asyncio.run`` too)."""

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


class FakeCore:
    def __init__(self) -> None:
        self.sessions: dict[str, BrainstormSession] = {}
        self.runs: dict[str, AgentRunView] = {}
        self.requests: list[dict[str, Any]] = []
        self.chain_runs: dict[tuple[str, str], AgentRunView] = {}
        self.saved: list[dict[str, Any]] = []
        self.configs = {
            r["role"]: r for r in brainstorm_seed_payloads() if r["role"] in RESEARCH_AGENT_NAMES
        }

    def add_session(self, **kw: Any) -> BrainstormSession:
        s = BrainstormSession(**{"id": "b1", "owner_sub": "alice", "status": BS_QUALIFYING, **kw})
        self.sessions[s.id] = s
        return s

    async def get_brainstorm_session(self, *, owner_sub, session_id):
        s = self.sessions.get(session_id)
        return s if s is not None and s.owner_sub == owner_sub else None

    async def update_brainstorm_session(self, *, session_id, **fields):
        self.sessions[session_id] = replace(self.sessions[session_id], **fields)

    async def get_own_config(self, *, role):
        return self.configs.get(role)

    async def request_agent_run(
        self, *, agent_name, definition, output_tool, input_payload, causation_id
    ):
        run_id = f"run-{len(self.requests)}"
        self.requests.append(
            {
                "agent_name": agent_name,
                "definition": definition,
                "input_payload": input_payload,
                "causation_id": causation_id,
                "id": run_id,
            }
        )
        self.runs[run_id] = AgentRunView(id=run_id, status="running", started_at="t")
        return run_id

    async def find_chain_run(self, *, chain_id, agent_name):
        return self.chain_runs.get((chain_id, agent_name))

    async def get_agent_run(self, *, run_id):
        return self.runs.get(run_id)

    async def save_brainstorm_opportunities(self, *, session_id, opportunities, model):
        self.saved = opportunities


def _svc(core: FakeCore) -> BrainstormService:
    return BrainstormService(cast(Any, core))


def _opps_messages(n: int = 3) -> list[dict[str, object]]:
    opps = [
        {"title": f"T{i}", "pitch": "p", "rationale": "r", "sources": [{"url": "u", "note": "n"}]}
        for i in range(n)
    ]
    return [
        {
            "tool_calls": [
                {
                    "function": {
                        "name": OPPORTUNITIES_TOOL_NAME,
                        "arguments": json.dumps({"opportunities": opps}),
                    }
                }
            ]
        }
    ]


async def _researching(core: FakeCore) -> BrainstormSession:
    core.add_session(target="dentists", geography="UK", problem="no-shows")
    return await _svc(core).finalise(owner_sub="alice", session_id="b1")


@_sync
async def test_finalise_fires_all_six_under_one_chain() -> None:
    core = FakeCore()
    session = await _researching(core)

    assert session.status == BS_RESEARCHING
    assert [r["agent_name"] for r in core.requests] == list(RESEARCH_AGENT_NAMES)
    chains = {r["causation_id"] for r in core.requests}
    assert chains == {session.chain_id}
    assert session.research_run_ids == [r["id"] for r in core.requests]
    assert core.sessions["b1"].status == BS_RESEARCHING
    brief = core.requests[0]["input_payload"]["brief"]
    assert brief["target"] == "dentists" and brief["geography"] == "UK"


@_sync
async def test_research_definitions_use_online_models_and_no_tools() -> None:
    core = FakeCore()
    await _researching(core)

    for r in core.requests:
        assert r["definition"]["tools"] == []
        assert r["definition"]["model"].endswith(":online")


def test_research_definition_never_lists_web_search() -> None:
    assert research_definition(model="m:online", instructions="x")["tools"] == []


@_sync
async def test_finalise_requires_qualifying_session() -> None:
    core = FakeCore()
    core.add_session(status=BS_RESEARCHING)
    with pytest.raises(NotGatheringError):
        await _svc(core).finalise(owner_sub="alice", session_id="b1")
    assert core.requests == []


@_sync
async def test_finalise_with_missing_config_raises_before_any_state_change() -> None:
    core = FakeCore()
    core.add_session(target="x")
    del core.configs[RESEARCH_AGENT_NAMES[-1]]
    with pytest.raises(AgentConfigMissingError):
        await _svc(core).finalise(owner_sub="alice", session_id="b1")
    assert core.sessions["b1"].status == BS_QUALIFYING


@_sync
async def test_still_researching_stays_put() -> None:
    core = FakeCore()
    session = await _researching(core)
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_RESEARCHING and got.chain_id == session.chain_id


@_sync
async def test_synthesis_run_discovered_advances_to_synthesising() -> None:
    core = FakeCore()
    session = await _researching(core)
    core.chain_runs[(session.chain_id, SYNTHESIS_AGENT_NAME)] = AgentRunView(
        id="syn", status="running", started_at="t"
    )
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_SYNTHESISING and got.synthesis_run_id == "syn"
    assert core.sessions["b1"].synthesis_run_id == "syn"


@_sync
async def test_all_research_failed_fails_the_session() -> None:
    core = FakeCore()
    await _researching(core)
    for rid in core.runs:
        core.runs[rid] = AgentRunView(id=rid, status="failed", started_at="t")
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_FAILED
    assert "failed to return usable findings" in (got.failure_reason or "")


@_sync
async def test_never_started_is_distinct_from_failed() -> None:
    core = FakeCore()
    await _researching(core)
    for rid in core.runs:
        core.runs[rid] = AgentRunView(id=rid, status="failed", started_at=None)
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_FAILED
    assert got.failure_reason == BrainstormService.NEVER_STARTED_REASON


@_sync
async def test_some_succeeded_terminal_does_not_race_the_engine_to_failure() -> None:
    core = FakeCore()
    await _researching(core)
    for i, rid in enumerate(core.runs):
        status = "completed" if i == 0 else "failed"
        core.runs[rid] = AgentRunView(id=rid, status=status, started_at="t")
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_RESEARCHING


async def _synthesising(core: FakeCore) -> None:
    core.add_session(
        status=BS_SYNTHESISING, chain_id="c", synthesis_run_id="syn", research_run_ids=[]
    )


@_sync
async def test_synthesis_success_saves_opportunities_and_completes() -> None:
    core = FakeCore()
    await _synthesising(core)
    core.runs["syn"] = AgentRunView(
        id="syn", status="completed", messages=_opps_messages(3), model="m", started_at="t"
    )
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_COMPLETE
    assert [o["title"] for o in core.saved] == ["T0", "T1", "T2"]
    assert core.saved[0]["evidence"] == [{"url": "u", "note": "n"}]


@_sync
async def test_synthesis_still_running_stays_put() -> None:
    core = FakeCore()
    await _synthesising(core)
    core.runs["syn"] = AgentRunView(id="syn", status="running", started_at="t")
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_SYNTHESISING


@_sync
async def test_synthesis_failed_fails_session() -> None:
    core = FakeCore()
    await _synthesising(core)
    core.runs["syn"] = AgentRunView(id="syn", status="failed", started_at="t")
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_FAILED
    assert got.failure_reason != BrainstormService.NEVER_STARTED_REASON


@_sync
async def test_synthesis_never_started() -> None:
    core = FakeCore()
    await _synthesising(core)
    core.runs["syn"] = AgentRunView(id="syn", status="failed", started_at=None)
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.failure_reason == BrainstormService.NEVER_STARTED_REASON


@_sync
async def test_synthesis_missing_run_fails() -> None:
    core = FakeCore()
    await _synthesising(core)
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_FAILED


@_sync
async def test_synthesis_without_tool_call_fails() -> None:
    core = FakeCore()
    await _synthesising(core)
    core.runs["syn"] = AgentRunView(id="syn", status="completed", started_at="t")
    got = await _svc(core).get_session(owner_sub="alice", session_id="b1")
    assert got.status == BS_FAILED and core.saved == []


@_sync
async def test_synthesis_empty_list_fails_and_overlong_is_trimmed() -> None:
    core = FakeCore()
    await _synthesising(core)
    core.runs["syn"] = AgentRunView(
        id="syn", status="completed", messages=_opps_messages(0), started_at="t"
    )
    assert (await _svc(core).get_session(owner_sub="alice", session_id="b1")).status == BS_FAILED

    core2 = FakeCore()
    await _synthesising(core2)
    core2.runs["syn"] = AgentRunView(
        id="syn", status="completed", messages=_opps_messages(14), started_at="t"
    )
    await _svc(core2).get_session(owner_sub="alice", session_id="b1")
    assert len(core2.saved) == 10


def test_eight_seed_roles_with_online_research_models() -> None:
    rows = brainstorm_seed_payloads()
    assert len(rows) == 8
    assert len({r["agent_key"] for r in rows}) == 8
    by = {r["role"]: r for r in rows}
    for name in RESEARCH_AGENT_NAMES:
        assert by[name]["model"].endswith(":online")
    assert not by[SYNTHESIS_AGENT_NAME]["model"].endswith(":online")
