"""The Ideation Engine's orchestration — transport-agnostic.

Pure async logic over the ``CoreGateway`` port: session lifecycle, the buffered
requirement-gathering chat (a thread of runs — ADR-0016 §2, *buffered* amendment),
finalising into the async analysis run, and turning that run's structured output
into the stored report. No HTTP, no AWS, no LLM SDK, and — deliberately — no
message assembly or fencing here: Core's trusted spine owns that (ADR-0016 §7).

What stays the plugin's own: the session state machine, the turn budget, owner
scoping, the two agent prompts (its actual IP), and report extraction.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import ValidationError

from .definitions import (
    ANALYST_AGENT_NAME,
    CHALLENGER_AGENT_NAME,
    CHALLENGER_INSTRUCTIONS,
    MAX_TURNS,
    MIN_TURNS,
    REPORT_TOOL_NAME,
    Report,
    analyst_definition,
    report_tool_schema,
)
from .models import (
    ANALYSING,
    COMPLETE,
    GATHERING,
    RUN_COMPLETED,
    RUN_TERMINAL,
    Session,
    TurnResult,
)
from .ports import CoreGateway


class IdeationError(Exception):
    """Base for orchestration errors the transport maps to HTTP statuses."""


class SessionNotFoundError(IdeationError):
    """No such session for this founder (missing, or owned by someone else)."""


class NotGatheringError(IdeationError):
    """The action needs a session still in the gathering phase."""


class TurnLimitReachedError(IdeationError):
    """The requirement-gathering conversation has hit its cap; finalise instead."""


class NotEnoughTurnsError(IdeationError):
    """Too few turns to produce a useful report yet."""


class MalformedReportError(IdeationError):
    """The analysis run finished without a valid structured report."""


class AnalysisFailedError(IdeationError):
    """The async analysis run failed; there is no report to produce."""


def extract_report(run_messages: list[dict[str, Any]]) -> Report:
    """Pull the analyst's structured verdict out of its run transcript: find the
    ``submit_ideation_report`` tool call and validate its arguments against
    ``Report``. Raises :class:`MalformedReportError` if it's missing or invalid."""
    for message in run_messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") != REPORT_TOOL_NAME:
                continue
            arguments = function.get("arguments")
            data = json.loads(arguments) if isinstance(arguments, str) else arguments
            try:
                return Report.model_validate(data)
            except ValidationError as exc:
                raise MalformedReportError(str(exc)) from exc
    raise MalformedReportError(f"the analysis run produced no {REPORT_TOOL_NAME} tool call")


class IdeationService:
    def __init__(
        self,
        core: CoreGateway,
        *,
        chat_model: str,
        analysis_model: str,
        min_turns: int = MIN_TURNS,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self._core = core
        self._chat_model = chat_model
        self._analysis_model = analysis_model
        self._min_turns = min_turns
        self._max_turns = max_turns

    async def start_session(self, *, owner_sub: str, seed_idea: str) -> Session:
        """Open a session for a founder's idea, in the gathering phase, with a
        fresh run thread to carry the conversation. The idea itself is not put in
        the challenger's system prompt — it is untrusted, and enters the thread as
        the first fenced user turn (the caller's first :meth:`chat_turn`)."""
        return await self._core.create_session(
            owner_sub=owner_sub,
            seed_idea=seed_idea.strip(),
            thread_id=str(uuid.uuid4()),
        )

    async def _load_owned(self, *, owner_sub: str, session_id: str) -> Session:
        session = await self._core.get_session(owner_sub=owner_sub, session_id=session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    async def get_session(self, *, owner_sub: str, session_id: str) -> Session:
        """The founder's session — its status and turn count, for the UI to poll
        (whether the chat may continue, and whether it may be finalised). Raises
        :class:`SessionNotFoundError` for a missing or non-owned session."""
        return await self._load_owned(owner_sub=owner_sub, session_id=session_id)

    async def list_sessions(self, *, owner_sub: str) -> list[Session]:
        """The founder's sessions, most-recent-first."""
        sessions = await self._core.list_sessions(owner_sub=owner_sub)
        return sorted(sessions, key=lambda s: s.created_at or "", reverse=True)

    async def chat_turn(self, *, owner_sub: str, session_id: str, user_message: str) -> TurnResult:
        """Run one buffered challenger turn and return the reply.

        The plugin only decides *whether* the turn may run (gathering, under the
        cap) and *with what* prompt (the challenger instructions) — it hands Core
        the founder's raw message and lets the trusted spine fence it, assemble the
        context, invoke the runtime, and persist the turn (ADR-0016 §7). Then it
        advances the turn counter.
        """
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != GATHERING:
            raise NotGatheringError(session.status)
        if session.turn_count >= self._max_turns:
            raise TurnLimitReachedError(self._max_turns)

        result = await self._core.run_chat_turn(
            thread_id=session.thread_id,
            owner_sub=owner_sub,
            agent_name=CHALLENGER_AGENT_NAME,
            system_prompt=CHALLENGER_INSTRUCTIONS,
            user_text=user_message,
            model=self._chat_model,
        )
        await self._core.set_turn_count(session_id=session_id, turn_count=session.turn_count + 1)
        return result

    async def finalise(self, *, owner_sub: str, session_id: str) -> str:
        """Kick the async analysis run over the whole conversation and move the
        session to ``analysing``. Returns the run id the caller can poll on. Core
        assembles the analyst's context from the thread — the seed idea is already
        its first turn — so nothing is re-passed here."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != GATHERING:
            raise NotGatheringError(session.status)
        if session.turn_count < self._min_turns:
            raise NotEnoughTurnsError(session.turn_count)

        run_id = await self._core.request_analysis(
            thread_id=session.thread_id,
            owner_sub=owner_sub,
            agent_name=ANALYST_AGENT_NAME,
            definition=analyst_definition(model=self._analysis_model),
            output_tool=report_tool_schema(),
        )
        await self._core.set_status(session_id=session_id, status=ANALYSING, analysis_run_id=run_id)
        return run_id

    async def get_report(self, *, owner_sub: str, session_id: str) -> dict[str, Any] | None:
        """The founder's report, or ``None`` while still gathering/analysing.

        This is where the analysis run is *materialised into the report* — lazily,
        on the founder's own poll, rather than pushed from an event subscriber. The
        chosen §5 trust model derives the owner from the founder's forwarded token,
        so every write must happen inside a founder request; a founder polling for
        their report is exactly such a request. Once complete the write is not
        repeated.

        Raises :class:`AnalysisFailedError` if the run failed, and :class:`MalformedReportError`
        if it finished without a valid structured report.
        """
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status == COMPLETE:
            return await self._core.get_report(session_id=session_id)
        if session.status != ANALYSING or session.analysis_run_id is None:
            return None  # still gathering, or not finalised

        run = await self._core.get_run(run_id=session.analysis_run_id)
        if run is None or run.status not in RUN_TERMINAL:
            return None  # the analysis is still in flight
        if run.status != RUN_COMPLETED:
            raise AnalysisFailedError(session_id)

        # Terminal + completed: extract, store, and mark complete — all under this
        # founder's request. `save_report` sends no owner; Core stamps it from the
        # forwarded token (ADR-0017 §5), so the report is owner-scoped like the
        # session.
        report = extract_report(run.messages)
        await self._core.save_report(
            session_id=session_id,
            prd=report.prd.model_dump(),
            scorecard=report.scorecard.model_dump(),
            model=run.model,
        )
        await self._core.set_status(session_id=session_id, status=COMPLETE)
        return await self._core.get_report(session_id=session_id)
