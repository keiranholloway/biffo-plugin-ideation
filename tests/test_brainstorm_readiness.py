"""Brain-Storming readiness signal, the qualifier's own ceiling, and the brief
reaching research (cause 5)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, cast

from ideation import definitions
from ideation.brainstorm_definitions import (
    BRIEF_STATE_CLOSE,
    BRIEF_STATE_OPEN,
    QUALIFIER_MAX_TURNS,
    brainstorm_seed_payloads,
    parse_brief_state,
)
from ideation.models import BS_QUALIFYING, AgentRunView, BrainstormSession, TurnResult
from ideation.service import BrainstormService, TurnLimitReachedError

BRIEF = {
    "ready": True,
    "summary": "Clinics lose revenue to no-shows",
    "what_the_business_wants": {
        "goals": "lifestyle business",
        "capabilities_and_assets": "ex-clinic manager",
        "target_customer": "UK physio clinics",
    },
    "business_problem": "no-shows",
    "size_and_shape": {
        "who_and_how_many": "12k clinics",
        "cost_and_frequency": "10% of slots",
        "current_workarounds": "SMS reminders",
        "boundaries_and_constraints": "GDPR",
    },
    "gaps": [],
}


def _block(state: dict[str, Any]) -> str:
    return f"{BRIEF_STATE_OPEN}{json.dumps(state)}{BRIEF_STATE_CLOSE}"


class FakeCore:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.session = BrainstormSession(
            id="b1", owner_sub="alice", status=BS_QUALIFYING, thread_id="t", target="dentists"
        )
        self.requests: list[dict[str, Any]] = []
        self.configs = {r["role"]: r for r in brainstorm_seed_payloads()}

    async def get_brainstorm_session(self, *, owner_sub, session_id):
        return self.session

    async def update_brainstorm_session(self, *, session_id, **fields):
        self.session = replace(self.session, **fields)

    async def run_chat_turn(self, *, thread_id, owner_sub, agent_name, user_text):
        return TurnResult(reply=self.replies.pop(0))

    async def get_own_config(self, *, role):
        return self.configs.get(role)

    async def request_agent_run(
        self, *, agent_name, definition, output_tool, input_payload, causation_id
    ):
        self.requests.append({"agent_name": agent_name, "input_payload": input_payload})
        return f"r{len(self.requests)}"

    async def get_agent_run(self, *, run_id):
        return AgentRunView(id=run_id, status="running", started_at="t")


def _turn(svc: BrainstormService) -> TurnResult:
    return asyncio.run(svc.chat_turn(owner_sub="alice", session_id="b1", user_message="hi"))


def test_ready_flips_only_on_the_structured_signal() -> None:
    core = FakeCore(
        [
            "The brief is READY and complete, press Run research.",  # prose only
            f"Still unclear. {_block({**BRIEF, 'ready': False, 'gaps': ['budget']})}",
            f"All clear. {_block(BRIEF)}",
            f"Garbled {BRIEF_STATE_OPEN}{{not json{BRIEF_STATE_CLOSE}",
        ]
    )
    svc = BrainstormService(cast(Any, core))
    _turn(svc)
    assert core.session.ready is False and core.session.brief is None
    _turn(svc)
    assert core.session.ready is False and core.session.gaps == ["budget"]
    reply = _turn(svc).reply
    assert core.session.ready is True
    assert BRIEF_STATE_OPEN not in reply and reply == "All clear."
    _turn(svc)  # malformed block: previous brief stands
    assert core.session.ready is True


def test_latest_brief_wins() -> None:
    core = FakeCore([_block(BRIEF), _block({**BRIEF, "ready": False, "business_problem": "x"})])
    svc = BrainstormService(cast(Any, core))
    _turn(svc)
    _turn(svc)
    assert core.session.ready is False
    assert core.session.brief["business_problem"] == "x"  # type: ignore[index]


def test_finalise_passes_structured_brief_to_all_six_research_agents() -> None:
    core = FakeCore([f"Ready. {_block(BRIEF)}"])
    svc = BrainstormService(cast(Any, core))
    _turn(svc)
    asyncio.run(svc.finalise(owner_sub="alice", session_id="b1"))
    assert len(core.requests) == 6
    for req in core.requests:
        assert req["input_payload"]["brief"]["qualified_brief"] == BRIEF


def test_qualifier_ceiling_is_separate_from_pressure_test_cap() -> None:
    assert definitions.MAX_TURNS == 5
    assert QUALIFIER_MAX_TURNS == 8
    assert QUALIFIER_MAX_TURNS != definitions.MAX_TURNS


def test_ceiling_stops_the_chat_but_not_research() -> None:
    core = FakeCore([])
    core.session = replace(core.session, turn_count=QUALIFIER_MAX_TURNS)
    svc = BrainstormService(cast(Any, core))
    try:
        _turn(svc)
        raise AssertionError("expected the ceiling")
    except TurnLimitReachedError:
        pass
    asyncio.run(svc.finalise(owner_sub="alice", session_id="b1"))
    assert len(core.requests) == 6


def test_parse_without_block_returns_none() -> None:
    assert parse_brief_state("just prose") == ("just prose", None)


def test_qualifier_prompt_mentions_early_option_and_ceiling():
    from src.ideation.brainstorm_definitions import (
        QUALIFIER_EARLY_RESEARCH_TURN,
        QUALIFIER_INSTRUCTIONS,
    )

    assert QUALIFIER_EARLY_RESEARCH_TURN == 3
    assert "what I've given so far" in QUALIFIER_INSTRUCTIONS
    assert "ceiling of\n8 exchanges" in QUALIFIER_INSTRUCTIONS
    assert "<brief_state>" in QUALIFIER_INSTRUCTIONS
