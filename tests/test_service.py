"""The orchestration logic, exercised end-to-end against an in-memory fake Core."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest
from ideation.definitions import (
    CHALLENGER_AGENT_NAME,
    CHALLENGER_INSTRUCTIONS,
    REPORT_TOOL_NAME,
)
from ideation.models import ANALYSING, COMPLETE, GATHERING, Session, TurnResult
from ideation.service import (
    IdeationService,
    MalformedReport,
    NotEnoughTurns,
    NotGathering,
    SessionNotFound,
    TurnLimitReached,
    extract_report,
)


class FakeCore:
    """Stands in for Core's buffered chat spine + data API. ``run_chat_turn`` does
    what the trusted spine does — appends the exchange to the thread and returns a
    reply — so the plugin never assembles or fences here."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.sessions: dict[str, Session] = {}
        self.threads: dict[str, list[dict[str, Any]]] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.turn_calls: list[dict[str, Any]] = []
        self.analysis_requests: list[dict[str, Any]] = []
        self._replies = replies or ["Why now?"]
        self._seq = 0

    async def create_session(
        self, *, owner_sub: str, seed_idea: str, thread_id: str
    ) -> Session:
        self._seq += 1
        session = Session(
            id=f"s{self._seq}",
            owner_sub=owner_sub,
            seed_idea=seed_idea,
            status=GATHERING,
            thread_id=thread_id,
            turn_count=0,
        )
        self.sessions[session.id] = session
        return session

    async def get_session(self, *, owner_sub: str, session_id: str) -> Session | None:
        session = self.sessions.get(session_id)
        if session is None or session.owner_sub != owner_sub:
            return None  # owner-scoped: another founder's session is invisible
        return session

    async def set_turn_count(self, *, session_id: str, turn_count: int) -> None:
        self.sessions[session_id] = replace(
            self.sessions[session_id], turn_count=turn_count
        )

    async def set_status(
        self, *, session_id: str, status: str, analysis_run_id: str | None = None
    ) -> None:
        current = self.sessions[session_id]
        self.sessions[session_id] = replace(
            current,
            status=status,
            analysis_run_id=analysis_run_id or current.analysis_run_id,
        )

    async def run_chat_turn(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        agent_name: str,
        system_prompt: str,
        user_text: str,
        model: str,
    ) -> TurnResult:
        self.turn_calls.append(
            {
                "thread_id": thread_id,
                "owner_sub": owner_sub,
                "agent_name": agent_name,
                "system_prompt": system_prompt,
                "user_text": user_text,
                "model": model,
            }
        )
        idx = len(self.turn_calls) - 1
        reply = self._replies[idx] if idx < len(self._replies) else self._replies[-1]
        # the spine persists the exchange in the thread
        self.threads.setdefault(thread_id, []).extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply},
            ]
        )
        return TurnResult(reply=reply, model=model, output_tokens=len(reply))

    async def request_analysis(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        agent_name: str,
        definition: dict[str, Any],
        output_tool: dict[str, Any],
    ) -> str:
        self.analysis_requests.append(
            {
                "thread_id": thread_id,
                "agent_name": agent_name,
                "definition": definition,
                "output_tool": output_tool,
            }
        )
        return "run-analysis-1"

    async def save_report(
        self,
        *,
        session_id: str,
        prd: dict[str, Any],
        scorecard: dict[str, Any],
        model: str | None,
    ) -> None:
        self.reports[session_id] = {"prd": prd, "scorecard": scorecard, "model": model}

    async def get_report(self, *, session_id: str) -> dict[str, Any] | None:
        return self.reports.get(session_id)


def _service(core: FakeCore, **kw: Any) -> IdeationService:
    return IdeationService(core, chat_model="chat/m", analysis_model="analysis/m", **kw)


def _report_payload(problem: str = "A real problem.") -> dict[str, Any]:
    axis = {"score": 3, "rationale": "grounded"}
    return {
        "prd": {
            "problem": problem,
            "target_users": ["coaches"],
            "workflows": ["onboard"],
            "data_entities": ["client"],
            "capabilities": ["billing"],
            "out_of_scope": ["mobile"],
        },
        "scorecard": {
            "viability": axis,
            "complexity": axis,
            "economic_moat": axis,
            "market_fit": axis,
            "build_vs_buy": "build",
            "competitors": [{"name": "Rival", "url": None, "note": "weak onboarding"}],
            "summary": "Promising.",
        },
    }


def _analysis_run(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": REPORT_TOOL_NAME,
                        "arguments": json.dumps(payload),
                    },
                }
            ],
        }
    ]


class TestChat:
    def test_start_opens_a_gathering_session_with_a_thread(self) -> None:
        svc = _service(FakeCore())
        session = asyncio.run(svc.start_session(owner_sub="u", seed_idea="  an idea  "))
        assert session.status == GATHERING
        assert session.turn_count == 0
        assert session.thread_id  # a run thread was allocated
        assert session.seed_idea == "an idea"  # trimmed

    def test_turn_drives_the_spine_and_advances_the_counter(self) -> None:
        core = FakeCore(replies=["Why now?"])
        svc = _service(core)

        async def scenario() -> tuple[Session, TurnResult]:
            s = await svc.start_session(owner_sub="u", seed_idea="an idea")
            result = await svc.chat_turn(
                owner_sub="u", session_id=s.id, user_message="It helps coaches."
            )
            return core.sessions[s.id], result

        session, result = asyncio.run(scenario())
        # the buffered reply came back whole
        assert result.reply == "Why now?"
        # exactly one spine call, with the plugin's prompt + the founder's RAW text
        assert len(core.turn_calls) == 1
        call = core.turn_calls[0]
        assert call["agent_name"] == CHALLENGER_AGENT_NAME
        assert call["system_prompt"] == CHALLENGER_INSTRUCTIONS
        assert call["user_text"] == "It helps coaches."  # unfenced — Core fences it
        assert call["model"] == "chat/m"
        # the counter advanced
        assert session.turn_count == 1

    def test_the_seed_idea_never_enters_the_system_prompt(self) -> None:
        # regression: the founder's idea is untrusted; it must not be concatenated
        # into the trusted instruction channel. It enters as the first user turn.
        core = FakeCore()
        svc = _service(core)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="u", seed_idea="SECRET-SEED")
            await svc.chat_turn(
                owner_sub="u", session_id=s.id, user_message="SECRET-SEED"
            )

        asyncio.run(scenario())
        assert "SECRET-SEED" not in core.turn_calls[0]["system_prompt"]
        assert core.turn_calls[0]["user_text"] == "SECRET-SEED"

    def test_turn_cap_is_enforced(self) -> None:
        svc = _service(FakeCore(), max_turns=2)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="u", seed_idea="idea")
            await svc.chat_turn(owner_sub="u", session_id=s.id, user_message="1")
            await svc.chat_turn(owner_sub="u", session_id=s.id, user_message="2")
            await svc.chat_turn(owner_sub="u", session_id=s.id, user_message="3")

        with pytest.raises(TurnLimitReached):
            asyncio.run(scenario())

    def test_another_founders_session_is_invisible(self) -> None:
        svc = _service(FakeCore())

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="alice", seed_idea="idea")
            await svc.chat_turn(owner_sub="mallory", session_id=s.id, user_message="hi")

        with pytest.raises(SessionNotFound):
            asyncio.run(scenario())


class TestFinaliseAndReport:
    def _gathered(self, core: FakeCore, svc: IdeationService, turns: int) -> str:
        async def scenario() -> str:
            s = await svc.start_session(owner_sub="u", seed_idea="idea")
            for i in range(turns):
                await svc.chat_turn(owner_sub="u", session_id=s.id, user_message=str(i))
            return s.id

        return asyncio.run(scenario())

    def test_finalise_requests_analysis_and_moves_to_analysing(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=2, max_turns=5)
        sid = self._gathered(core, svc, turns=3)

        run_id = asyncio.run(svc.finalise(owner_sub="u", session_id=sid))
        assert run_id == "run-analysis-1"
        assert core.sessions[sid].status == ANALYSING
        assert core.sessions[sid].analysis_run_id == run_id
        # Core was handed the analyst definition + the structured-output tool schema
        req = core.analysis_requests[0]
        assert req["thread_id"] == core.sessions[sid].thread_id
        assert req["output_tool"]["function"]["name"] == REPORT_TOOL_NAME
        assert "web_search" in req["definition"]["tools"]

    def test_finalise_needs_enough_turns(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=3)
        sid = self._gathered(core, svc, turns=1)
        with pytest.raises(NotEnoughTurns):
            asyncio.run(svc.finalise(owner_sub="u", session_id=sid))

    def test_cannot_finalise_twice(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            await svc.finalise(owner_sub="u", session_id=sid)
            await svc.finalise(owner_sub="u", session_id=sid)

        with pytest.raises(NotGathering):
            asyncio.run(scenario())

    def test_cannot_chat_after_finalising(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            await svc.finalise(owner_sub="u", session_id=sid)
            await svc.chat_turn(owner_sub="u", session_id=sid, user_message="more")

        with pytest.raises(NotGathering):
            asyncio.run(scenario())

    def test_complete_stores_the_report_and_marks_complete(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> dict[str, Any] | None:
            await svc.finalise(owner_sub="u", session_id=sid)
            # still analysing → no report yet
            assert await svc.get_report(owner_sub="u", session_id=sid) is None
            await svc.complete_analysis(
                session_id=sid,
                run_messages=_analysis_run(_report_payload("Coaches!")),
                model="m",
            )
            return await svc.get_report(owner_sub="u", session_id=sid)

        report = asyncio.run(scenario())
        assert core.sessions[sid].status == COMPLETE
        assert report is not None
        assert report["prd"]["problem"] == "Coaches!"
        assert report["scorecard"]["viability"]["score"] == 3
        assert report["model"] == "m"


class TestExtractReport:
    def test_valid_tool_call(self) -> None:
        report = extract_report(_analysis_run(_report_payload("X")))
        assert report.prd.problem == "X"
        assert report.scorecard.build_vs_buy == "build"

    def test_missing_tool_call_is_malformed(self) -> None:
        with pytest.raises(MalformedReport):
            extract_report([{"role": "assistant", "content": "I couldn't decide."}])

    def test_invalid_arguments_are_malformed(self) -> None:
        bad = _report_payload()
        bad["scorecard"]["viability"]["score"] = 99  # out of 1–5
        with pytest.raises(MalformedReport):
            extract_report(_analysis_run(bad))
