"""The orchestration logic, exercised end-to-end against an in-memory fake Core."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest

from ideation.definitions import (
    ANALYST_INSTRUCTIONS,
    CHALLENGER_AGENT_NAME,
    REPORT_TOOL_NAME,
)
from ideation.models import ANALYSING, COMPLETE, GATHERING, Run, Session, TurnResult
from ideation.service import (
    AnalysisFailedError,
    IdeationService,
    MalformedReportError,
    NotEnoughTurnsError,
    NotGatheringError,
    SessionNotFoundError,
    TurnLimitReachedError,
    extract_report,
)

#: What Core reports a challenger turn ran on. Resolved from the stored
#: chat-agent row, server-side; nothing in this plugin selects it. The fake used
#: to echo back the caller's own ``model`` argument, which made a parameter the
#: adapter discarded look like it round-tripped (issue #68).
CORE_RESOLVED_MODEL = "core-resolved/challenger"


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
        self.runs: dict[str, Run] = {}
        self._replies = replies or ["Why now?"]
        self._seq = 0
        self._submitted_idea: str | None = None
        self._own_config: dict[str, dict[str, Any]] = {}
        self._active_agents: dict[str, list[dict[str, Any]]] = {}

    # test helper: drive the async analysis run to a terminal state
    def resolve_run(
        self,
        run_id: str,
        *,
        status: str,
        messages: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> None:
        self.runs[run_id] = Run(id=run_id, status=status, messages=messages or [], model=model)

    async def create_session(
        self, *, owner_sub: str, seed_idea: str, thread_id: str, challenger_agent_key: str
    ) -> Session:
        self._seq += 1
        session = Session(
            id=f"s{self._seq}",
            owner_sub=owner_sub,
            seed_idea=seed_idea,
            status=GATHERING,
            thread_id=thread_id,
            turn_count=0,
            challenger_agent_key=challenger_agent_key,
        )
        self.sessions[session.id] = session
        return session

    async def get_session(self, *, owner_sub: str, session_id: str) -> Session | None:
        session = self.sessions.get(session_id)
        if session is None or session.owner_sub != owner_sub:
            return None  # owner-scoped: another founder's session is invisible
        return session

    async def list_sessions(self, *, owner_sub: str) -> list[Session]:
        """Return sessions owned by this founder, in no particular order."""
        return [s for s in self.sessions.values() if s.owner_sub == owner_sub]

    async def set_turn_count(self, *, session_id: str, turn_count: int) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], turn_count=turn_count)

    async def set_status(
        self, *, session_id: str, status: str, analysis_run_id: str | None = None
    ) -> None:
        current = self.sessions[session_id]
        self.sessions[session_id] = replace(
            current,
            status=status,
            analysis_run_id=analysis_run_id or current.analysis_run_id,
        )

    async def delete_session(self, *, session_id: str) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], deleted=True)

    async def run_chat_turn(
        self, *, thread_id: str, owner_sub: str, agent_name: str, user_text: str
    ) -> TurnResult:
        self.turn_calls.append(
            {
                "thread_id": thread_id,
                "owner_sub": owner_sub,
                "agent_name": agent_name,
                "user_text": user_text,
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
        return TurnResult(reply=reply, model=CORE_RESOLVED_MODEL, output_tokens=len(reply))

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
        run_id = "run-analysis-1"
        # the run starts in flight; a test drives it terminal via resolve_run
        self.runs[run_id] = Run(id=run_id, status="running", messages=[])
        return run_id

    async def get_run(self, *, run_id: str) -> Run | None:
        return self.runs.get(run_id)

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

    async def get_submitted_idea(self, *, owner_sub: str) -> str | None:
        """Returns a submitted idea or None if not found."""
        # For testing, can be populated by the test
        return getattr(self, "_submitted_idea", None)

    async def get_own_config(self, *, role: str) -> dict[str, Any] | None:
        """Populated per-test via _own_config: {role: {system_prompt, model}}."""
        return self._own_config.get(role)

    async def list_active_agents(self, *, role: str) -> list[dict[str, Any]]:
        """Populated per-test via _active_agents: {role: [{agent_key, agent_name}, ...]}."""
        return self._active_agents.get(role, [])


def _service(core: FakeCore, **kw: Any) -> IdeationService:
    return IdeationService(core, analysis_model="analysis/m", **kw)


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
        # exactly one spine call, carrying the agent key and the founder's RAW text
        assert len(core.turn_calls) == 1
        call = core.turn_calls[0]
        assert call["agent_name"] == CHALLENGER_AGENT_NAME
        assert call["user_text"] == "It helps coaches."  # unfenced — Core fences it
        # ...and nothing else. Core resolves the prompt and model from the
        # agent's registration, which with chat_agents_dynamic on is the stored
        # row; a prompt or model sent from here would claim control this side
        # does not have (issue #68).
        assert set(call) == {"thread_id", "owner_sub", "agent_name", "user_text"}
        # the model on the result is Core's answer, not this plugin's request
        assert result.model == CORE_RESOLVED_MODEL
        # the counter advanced
        assert session.turn_count == 1

    def test_the_challenger_prompt_and_model_are_not_sent_at_all(self) -> None:
        """The port has no parameter for either, so there is nothing to discard.

        The previous signature required both and the adapter dropped them,
        which read as "the challenger runs on this constant and its stored row
        is inert" — the wrong diagnosis reached while investigating #58. Wiring
        them through would have made that true.
        """
        import inspect

        from ideation.adapter import CoreHttpGateway
        from ideation.ports import CoreGateway

        for impl in (CoreGateway, CoreHttpGateway):
            params = set(inspect.signature(impl.run_chat_turn).parameters)
            assert "system_prompt" not in params
            assert "model" not in params

        # ...and the service holds no chat model to pass.
        assert "chat_model" not in inspect.signature(IdeationService.__init__).parameters

    def test_the_seed_idea_never_enters_the_instruction_channel(self) -> None:
        # regression: the founder's idea is untrusted; it must not be concatenated
        # into the trusted instruction channel. It enters as the first user turn.
        # Since #68 the guarantee is structural rather than a value check —
        # there is no instruction channel on this call for it to leak into.
        core = FakeCore()
        svc = _service(core)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="u", seed_idea="SECRET-SEED")
            await svc.chat_turn(owner_sub="u", session_id=s.id, user_message="SECRET-SEED")

        asyncio.run(scenario())
        call = core.turn_calls[0]
        assert call["user_text"] == "SECRET-SEED"
        assert [k for k, v in call.items() if v == "SECRET-SEED"] == ["user_text"]

    def test_turn_cap_is_enforced(self) -> None:
        svc = _service(FakeCore(), max_turns=2)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="u", seed_idea="idea")
            await svc.chat_turn(owner_sub="u", session_id=s.id, user_message="1")
            await svc.chat_turn(owner_sub="u", session_id=s.id, user_message="2")
            await svc.chat_turn(owner_sub="u", session_id=s.id, user_message="3")

        with pytest.raises(TurnLimitReachedError):
            asyncio.run(scenario())

    def test_another_founders_session_is_invisible(self) -> None:
        svc = _service(FakeCore())

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="alice", seed_idea="idea")
            await svc.chat_turn(owner_sub="mallory", session_id=s.id, user_message="hi")

        with pytest.raises(SessionNotFoundError):
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
        assert "tools" not in req["definition"]

    def test_finalise_uses_the_live_analyst_config_when_set(self) -> None:
        core = FakeCore()
        core._own_config["analyst"] = {
            "system_prompt": "A live-edited analyst prompt.",
            "model": "some/live-model",
        }
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        asyncio.run(svc.finalise(owner_sub="u", session_id=sid))

        req = core.analysis_requests[0]
        assert req["definition"]["instructions"] == "A live-edited analyst prompt."
        assert req["definition"]["model"] == "some/live-model"

    def test_finalise_falls_back_to_the_built_in_analyst_when_unconfigured(self) -> None:
        core = FakeCore()  # no _own_config["analyst"] set
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        asyncio.run(svc.finalise(owner_sub="u", session_id=sid))

        req = core.analysis_requests[0]
        assert req["definition"]["instructions"] == ANALYST_INSTRUCTIONS
        assert req["definition"]["model"] == "analysis/m"  # _service()'s default

    def test_finalise_needs_enough_turns(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=3)
        sid = self._gathered(core, svc, turns=1)
        with pytest.raises(NotEnoughTurnsError):
            asyncio.run(svc.finalise(owner_sub="u", session_id=sid))

    def test_cannot_finalise_twice(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            await svc.finalise(owner_sub="u", session_id=sid)
            await svc.finalise(owner_sub="u", session_id=sid)

        with pytest.raises(NotGatheringError):
            asyncio.run(scenario())

    def test_cannot_chat_after_finalising(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            await svc.finalise(owner_sub="u", session_id=sid)
            await svc.chat_turn(owner_sub="u", session_id=sid, user_message="more")

        with pytest.raises(NotGatheringError):
            asyncio.run(scenario())

    def test_get_report_materialises_the_completed_run_lazily(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> dict[str, Any] | None:
            run_id = await svc.finalise(owner_sub="u", session_id=sid)
            # while the run is still in flight, polling yields no report yet...
            assert await svc.get_report(owner_sub="u", session_id=sid) is None
            assert core.sessions[sid].status == ANALYSING
            # ...the analyst run completes with its structured tool call...
            core.resolve_run(
                run_id,
                status="completed",
                messages=_analysis_run(_report_payload("Coaches!")),
                model="m",
            )
            # ...and the next poll materialises + stores it under this founder.
            return await svc.get_report(owner_sub="u", session_id=sid)

        report = asyncio.run(scenario())
        assert core.sessions[sid].status == COMPLETE
        assert report is not None
        assert report["prd"]["problem"] == "Coaches!"
        assert report["scorecard"]["viability"]["score"] == 3
        assert report["model"] == "m"

    def test_report_is_only_materialised_once(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            run_id = await svc.finalise(owner_sub="u", session_id=sid)
            core.resolve_run(
                run_id,
                status="completed",
                messages=_analysis_run(_report_payload()),
                model="m",
            )
            await svc.get_report(owner_sub="u", session_id=sid)  # materialises → COMPLETE
            # A second poll on a COMPLETE session reads the stored report, it does not
            # re-extract from the run (which a test could no longer even resolve).
            core.runs.clear()
            again = await svc.get_report(owner_sub="u", session_id=sid)
            assert again is not None

        asyncio.run(scenario())

    def test_a_failed_analysis_run_surfaces(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            run_id = await svc.finalise(owner_sub="u", session_id=sid)
            core.resolve_run(run_id, status="failed")
            await svc.get_report(owner_sub="u", session_id=sid)

        with pytest.raises(AnalysisFailedError):
            asyncio.run(scenario())

    def test_a_completed_run_without_a_report_is_malformed(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)
        sid = self._gathered(core, svc, turns=1)

        async def scenario() -> None:
            run_id = await svc.finalise(owner_sub="u", session_id=sid)
            core.resolve_run(
                run_id,
                status="completed",
                messages=[{"role": "assistant", "content": "no tool call"}],
            )
            await svc.get_report(owner_sub="u", session_id=sid)

        with pytest.raises(MalformedReportError):
            asyncio.run(scenario())


class TestListSessions:
    def test_list_sessions_returns_owner_sessions_sorted_by_recency(self) -> None:
        core = FakeCore()
        svc = _service(core)

        async def scenario() -> list[Session]:
            # Create sessions with deliberately out-of-order created_at values
            s1 = await svc.start_session(owner_sub="alice", seed_idea="second")
            s1 = replace(s1, created_at="2026-07-23T10:00:00Z")
            core.sessions[s1.id] = s1

            s2 = await svc.start_session(owner_sub="alice", seed_idea="newest")
            s2 = replace(s2, created_at="2026-07-25T15:00:00Z")
            core.sessions[s2.id] = s2

            s3 = await svc.start_session(owner_sub="alice", seed_idea="oldest")
            s3 = replace(s3, created_at="2026-07-20T09:00:00Z")
            core.sessions[s3.id] = s3

            # Another founder's session should not appear
            other = await svc.start_session(owner_sub="bob", seed_idea="bob's idea")
            other = replace(other, created_at="2026-07-26T20:00:00Z")
            core.sessions[other.id] = other

            return await svc.list_sessions(owner_sub="alice")

        sessions = asyncio.run(scenario())
        # Alice's sessions in most-recent-first order
        assert len(sessions) == 3
        assert sessions[0].created_at == "2026-07-25T15:00:00Z"
        assert sessions[1].created_at == "2026-07-23T10:00:00Z"
        assert sessions[2].created_at == "2026-07-20T09:00:00Z"
        # Bob's session did not appear
        assert all(s.owner_sub == "alice" for s in sessions)

    def test_list_sessions_handles_sessions_without_created_at(self) -> None:
        core = FakeCore()
        svc = _service(core)

        async def scenario() -> list[Session]:
            # Sessions without created_at (empty string sorts to the end)
            s1 = await svc.start_session(owner_sub="alice", seed_idea="idea1")
            s1 = replace(s1, created_at=None)
            core.sessions[s1.id] = s1

            s2 = await svc.start_session(owner_sub="alice", seed_idea="idea2")
            s2 = replace(s2, created_at="2026-07-25T10:00:00Z")
            core.sessions[s2.id] = s2

            return await svc.list_sessions(owner_sub="alice")

        sessions = asyncio.run(scenario())
        assert len(sessions) == 2
        # Session with created_at sorts first (most recent)
        assert sessions[0].created_at == "2026-07-25T10:00:00Z"
        # Session without created_at sorts last
        assert sessions[1].created_at is None


class TestDeleteSession:
    def test_delete_session_owned_by_founder_succeeds(self) -> None:
        core = FakeCore()
        svc = _service(core)

        async def scenario() -> str:
            s = await svc.start_session(owner_sub="alice", seed_idea="idea")
            await svc.delete_session(owner_sub="alice", session_id=s.id)
            return s.id

        session_id = asyncio.run(scenario())
        # Verify the session is marked as deleted
        assert core.sessions[session_id].deleted is True

    def test_delete_session_not_owned_raises_not_found(self) -> None:
        core = FakeCore()
        svc = _service(core)

        async def scenario() -> None:
            s = await svc.start_session(owner_sub="alice", seed_idea="idea")
            await svc.delete_session(owner_sub="mallory", session_id=s.id)

        with pytest.raises(SessionNotFoundError):
            asyncio.run(scenario())

    def test_delete_session_in_gathering_and_analysing_status(self) -> None:
        core = FakeCore()
        svc = _service(core, min_turns=1)

        async def scenario() -> tuple[str, str]:
            # Test deletion from gathering status
            s1 = await svc.start_session(owner_sub="alice", seed_idea="idea1")
            await svc.delete_session(owner_sub="alice", session_id=s1.id)

            # Test deletion from analysing status
            s2 = await svc.start_session(owner_sub="alice", seed_idea="idea2")
            await svc.chat_turn(owner_sub="alice", session_id=s2.id, user_message="msg")
            await svc.finalise(owner_sub="alice", session_id=s2.id)
            await svc.delete_session(owner_sub="alice", session_id=s2.id)
            return (s1.id, s2.id)

        s1_id, s2_id = asyncio.run(scenario())
        assert core.sessions[s1_id].deleted is True
        assert core.sessions[s2_id].deleted is True

    def test_list_sessions_excludes_deleted(self) -> None:
        core = FakeCore()
        svc = _service(core)

        async def scenario() -> tuple[str, str, list[str]]:
            s1 = await svc.start_session(owner_sub="alice", seed_idea="keep")
            s2 = await svc.start_session(owner_sub="alice", seed_idea="delete")
            await svc.delete_session(owner_sub="alice", session_id=s2.id)
            sessions = await svc.list_sessions(owner_sub="alice")
            return (s1.id, s2.id, [s.id for s in sessions])

        s1_id, s2_id, session_ids = asyncio.run(scenario())
        assert len(session_ids) == 1
        assert s1_id in session_ids
        assert s2_id not in session_ids


class TestExtractReport:
    def test_valid_tool_call(self) -> None:
        report = extract_report(_analysis_run(_report_payload("X")))
        assert report.prd.problem == "X"
        assert report.scorecard.build_vs_buy == "build"

    def test_missing_tool_call_is_malformed(self) -> None:
        with pytest.raises(MalformedReportError):
            extract_report([{"role": "assistant", "content": "I couldn't decide."}])

    def test_invalid_arguments_are_malformed(self) -> None:
        bad = _report_payload()
        bad["scorecard"]["viability"]["score"] = 99  # out of 1–5
        with pytest.raises(MalformedReportError):
            extract_report(_analysis_run(bad))


class TestSubmittedIdea:
    def test_get_submitted_idea_returns_the_idea(self) -> None:
        core = FakeCore()
        core._submitted_idea = "build a coaching app"
        svc = _service(core)

        idea = asyncio.run(svc.get_submitted_idea(owner_sub="u"))

        assert idea == "build a coaching app"

    def test_get_submitted_idea_returns_none_if_not_submitted(self) -> None:
        core = FakeCore()
        svc = _service(core)

        idea = asyncio.run(svc.get_submitted_idea(owner_sub="u"))

        assert idea is None
