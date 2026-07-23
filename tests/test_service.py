"""The orchestration logic, exercised end-to-end against in-memory fakes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
from ideation.definitions import REPORT_TOOL_NAME
from ideation.models import ANALYSING, COMPLETE, GATHERING, Session, StreamChunk, Usage
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
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.threads: dict[str, list[dict[str, Any]]] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.analysis_requests: list[dict[str, Any]] = []
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

    async def thread_messages(self, *, thread_id: str) -> list[dict[str, Any]]:
        return list(self.threads.get(thread_id, []))

    async def record_turn(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        definition: dict[str, Any],
        user_message: str,
        assistant_message: str,
        usage: object | None,
    ) -> None:
        self.threads.setdefault(thread_id, []).extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
        )

    async def request_analysis(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        definition: dict[str, Any],
        conversation: list[dict[str, Any]],
    ) -> str:
        self.analysis_requests.append(
            {"thread_id": thread_id, "conversation": conversation}
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


class FakeStreamer:
    def __init__(self, deltas: list[str]) -> None:
        self.deltas = deltas
        self.calls: list[dict[str, Any]] = []

    def stream(
        self, *, model: str, messages: list[dict[str, Any]]
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append({"model": model, "messages": messages})

        async def _gen() -> AsyncIterator[StreamChunk]:
            for delta in self.deltas:
                yield StreamChunk(delta=delta)
            yield StreamChunk(
                done=Usage(
                    content="".join(self.deltas),
                    model=model,
                    output_tokens=len(self.deltas),
                )
            )

        return _gen()


def _service(core: FakeCore, streamer: FakeStreamer, **kw: Any) -> IdeationService:
    return IdeationService(
        core, streamer, chat_model="chat/m", analysis_model="analysis/m", **kw
    )


async def _collect(agen: AsyncIterator[str]) -> list[str]:
    return [chunk async for chunk in agen]


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
        core, streamer = FakeCore(), FakeStreamer([])
        svc = _service(core, streamer)
        session = asyncio.run(svc.start_session(owner_sub="u", seed_idea="  an idea  "))
        assert session.status == GATHERING
        assert session.turn_count == 0
        assert session.thread_id  # a run thread was allocated
        assert session.seed_idea == "an idea"  # trimmed

    def test_turn_streams_records_and_advances_the_counter(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["Wh", "y now?"])
        svc = _service(core, streamer)

        async def scenario() -> tuple[Session, list[str]]:
            s = await svc.start_session(owner_sub="u", seed_idea="an idea")
            deltas = await _collect(
                svc.chat_turn(
                    owner_sub="u", session_id=s.id, user_message="It helps coaches."
                )
            )
            return core.sessions[s.id], deltas

        session, deltas = asyncio.run(scenario())
        # streamed to the caller
        assert deltas == ["Wh", "y now?"]
        # context: system carries the idea; the user's message is last
        sent = streamer.calls[0]["messages"]
        assert sent[0]["role"] == "system" and "an idea" in sent[0]["content"]
        assert sent[-1] == {"role": "user", "content": "It helps coaches."}
        # the turn was recorded to the thread and the counter advanced
        assert session.turn_count == 1
        assert core.threads[session.thread_id] == [
            {"role": "user", "content": "It helps coaches."},
            {"role": "assistant", "content": "Why now?"},
        ]

    def test_second_turn_includes_prior_history_as_context(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["ok"])
        svc = _service(core, streamer)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="u", seed_idea="idea")
            await _collect(
                svc.chat_turn(owner_sub="u", session_id=s.id, user_message="first")
            )
            await _collect(
                svc.chat_turn(owner_sub="u", session_id=s.id, user_message="second")
            )

        asyncio.run(scenario())
        # the second call saw the first turn's user+assistant messages
        second_context = streamer.calls[1]["messages"]
        contents = [m["content"] for m in second_context]
        assert "first" in contents and "second" in contents

    def test_turn_cap_is_enforced(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["x"])
        svc = _service(core, streamer, max_turns=2)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="u", seed_idea="idea")
            await _collect(
                svc.chat_turn(owner_sub="u", session_id=s.id, user_message="1")
            )
            await _collect(
                svc.chat_turn(owner_sub="u", session_id=s.id, user_message="2")
            )
            await _collect(
                svc.chat_turn(owner_sub="u", session_id=s.id, user_message="3")
            )

        with pytest.raises(TurnLimitReached):
            asyncio.run(scenario())

    def test_another_founders_session_is_invisible(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["x"])
        svc = _service(core, streamer)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="alice", seed_idea="idea")
            await _collect(
                svc.chat_turn(owner_sub="mallory", session_id=s.id, user_message="hi")
            )

        with pytest.raises(SessionNotFound):
            asyncio.run(scenario())


class TestFinaliseAndReport:
    def _gathered(self, core: FakeCore, svc: IdeationService, turns: int) -> str:
        async def scenario() -> str:
            s = await svc.start_session(owner_sub="u", seed_idea="idea")
            for i in range(turns):
                await _collect(
                    svc.chat_turn(owner_sub="u", session_id=s.id, user_message=str(i))
                )
            return s.id

        return asyncio.run(scenario())

    def test_finalise_requests_analysis_and_moves_to_analysing(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["x"])
        svc = _service(core, streamer, min_turns=2, max_turns=5)
        sid = self._gathered(core, svc, turns=3)

        run_id = asyncio.run(svc.finalise(owner_sub="u", session_id=sid))
        assert run_id == "run-analysis-1"
        assert core.sessions[sid].status == ANALYSING
        assert core.sessions[sid].analysis_run_id == run_id
        # the analysis was handed the idea + the conversation
        convo = core.analysis_requests[0]["conversation"]
        assert "idea" in convo[0]["content"]
        assert len(convo) > 1

    def test_finalise_needs_enough_turns(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["x"])
        svc = _service(core, streamer, min_turns=3)
        sid = self._gathered(core, svc, turns=1)
        with pytest.raises(NotEnoughTurns):
            asyncio.run(svc.finalise(owner_sub="u", session_id=sid))

    def test_cannot_finalise_twice(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["x"])
        svc = _service(core, streamer, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            await svc.finalise(owner_sub="u", session_id=sid)
            await svc.finalise(owner_sub="u", session_id=sid)

        with pytest.raises(NotGathering):
            asyncio.run(scenario())

    def test_complete_stores_the_report_and_marks_complete(self) -> None:
        core, streamer = FakeCore(), FakeStreamer(["x"])
        svc = _service(core, streamer, min_turns=1)
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
