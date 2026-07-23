"""The Ideation Engine's orchestration — transport-agnostic.

Pure async logic over the ``CoreGateway`` and ``Streamer`` ports: session
lifecycle, the streamed requirement-gathering chat (a thread of runs, ADR-0016
§2), finalising into the async analysis run, and turning that run's structured
output into the stored report. No HTTP, no AWS, no LLM SDK here — the Function-URL
transport and the run_as:user identity adapter wrap this from outside.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError

from .definitions import (
    MAX_TURNS,
    MIN_TURNS,
    REPORT_TOOL_NAME,
    Report,
    analyst_definition,
    challenger_definition,
)
from .models import ANALYSING, COMPLETE, GATHERING, Session
from .ports import CoreGateway, Streamer


class IdeationError(Exception):
    """Base for orchestration errors the transport maps to HTTP statuses."""


class SessionNotFound(IdeationError):
    """No such session for this founder (missing, or owned by someone else)."""


class NotGathering(IdeationError):
    """The action needs a session still in the gathering phase."""


class TurnLimitReached(IdeationError):
    """The requirement-gathering conversation has hit its cap; finalise instead."""


class NotEnoughTurns(IdeationError):
    """Too few turns to produce a useful report yet."""


class MalformedReport(IdeationError):
    """The analysis run finished without a valid structured report."""


def extract_report(run_messages: list[dict[str, Any]]) -> Report:
    """Pull the analyst's structured verdict out of its run transcript: find the
    ``submit_ideation_report`` tool call and validate its arguments against
    ``Report``. Raises :class:`MalformedReport` if it's missing or invalid."""
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
                raise MalformedReport(str(exc)) from exc
    raise MalformedReport(f"the analysis run produced no {REPORT_TOOL_NAME} tool call")


class IdeationService:
    def __init__(
        self,
        core: CoreGateway,
        streamer: Streamer,
        *,
        chat_model: str,
        analysis_model: str,
        min_turns: int = MIN_TURNS,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self._core = core
        self._streamer = streamer
        self._chat_model = chat_model
        self._analysis_model = analysis_model
        self._min_turns = min_turns
        self._max_turns = max_turns

    async def start_session(self, *, owner_sub: str, seed_idea: str) -> Session:
        """Open a session for a founder's idea, in the gathering phase, with a
        fresh run thread to carry the conversation."""
        return await self._core.create_session(
            owner_sub=owner_sub,
            seed_idea=seed_idea.strip(),
            thread_id=str(uuid.uuid4()),
        )

    async def _load_owned(self, *, owner_sub: str, session_id: str) -> Session:
        session = await self._core.get_session(
            owner_sub=owner_sub, session_id=session_id
        )
        if session is None:
            raise SessionNotFound(session_id)
        return session

    async def chat_turn(
        self, *, owner_sub: str, session_id: str, user_message: str
    ) -> AsyncIterator[str]:
        """Stream one challenger turn: assemble the thread history as context, call
        the streaming client, yield the reply as it arrives, then record the turn
        as a run in the thread and advance the turn counter.

        An async generator — the transport streams the yielded deltas to the
        browser; the persistence happens once the stream is exhausted.
        """
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != GATHERING:
            raise NotGathering(session.status)
        if session.turn_count >= self._max_turns:
            raise TurnLimitReached(self._max_turns)

        definition = challenger_definition(model=self._chat_model)
        history = await self._core.thread_messages(thread_id=session.thread_id)
        system = (
            f"{definition['instructions']}\n\nThe founder's idea:\n{session.seed_idea}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *history,
            {"role": "user", "content": user_message},
        ]

        parts: list[str] = []
        usage: object | None = None
        async for chunk in self._streamer.stream(
            model=definition["model"], messages=messages
        ):
            if chunk.done is not None:
                usage = chunk.done
            elif chunk.delta:
                parts.append(chunk.delta)
                yield chunk.delta

        await self._core.record_turn(
            thread_id=session.thread_id,
            owner_sub=owner_sub,
            definition=definition,
            user_message=user_message,
            assistant_message="".join(parts),
            usage=usage,
        )
        await self._core.set_turn_count(
            session_id=session_id, turn_count=session.turn_count + 1
        )

    async def finalise(self, *, owner_sub: str, session_id: str) -> str:
        """Kick the async analysis run over the whole conversation and move the
        session to ``analysing``. Returns the run id the caller can poll on."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != GATHERING:
            raise NotGathering(session.status)
        if session.turn_count < self._min_turns:
            raise NotEnoughTurns(session.turn_count)

        definition = analyst_definition(model=self._analysis_model)
        conversation = await self._core.thread_messages(thread_id=session.thread_id)
        run_id = await self._core.request_analysis(
            thread_id=session.thread_id,
            owner_sub=owner_sub,
            definition=definition,
            conversation=[
                {
                    "role": "user",
                    "content": f"The founder's idea:\n{session.seed_idea}",
                },
                *conversation,
            ],
        )
        await self._core.set_status(
            session_id=session_id, status=ANALYSING, analysis_run_id=run_id
        )
        return run_id

    async def complete_analysis(
        self,
        *,
        session_id: str,
        run_messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> None:
        """Called when the analysis run completes (the ``agent.run.completed``
        subscriber): extract the structured report from the run, store it, and
        mark the session complete."""
        report = extract_report(run_messages)
        await self._core.save_report(
            session_id=session_id,
            prd=report.prd.model_dump(),
            scorecard=report.scorecard.model_dump(),
            model=model,
        )
        await self._core.set_status(session_id=session_id, status=COMPLETE)

    async def get_report(
        self, *, owner_sub: str, session_id: str
    ) -> dict[str, Any] | None:
        """The founder's report, or ``None`` while still gathering/analysing."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != COMPLETE:
            return None
        return await self._core.get_report(session_id=session_id)
