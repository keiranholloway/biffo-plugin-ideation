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

import dataclasses
import json
import uuid
from typing import Any

from pydantic import ValidationError

from .brainstorm_definitions import (
    FINDINGS_TOOL_NAME,
    MAX_OPPORTUNITIES,
    OPPORTUNITIES_TOOL_NAME,
    QUALIFIER_AGENT_NAME,
    QUALIFIER_MAX_TURNS,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    FindingSet,
    OpportunitySet,
    findings_tool_schema,
    parse_brief_state,
    research_definition,
)
from .definitions import (
    ANALYST_AGENT_NAME,
    CHALLENGER_AGENT_NAME,
    MAX_TURNS,
    MIN_TURNS,
    REPORT_TOOL_NAME,
    Report,
    analyst_definition,
    report_tool_schema,
)
from .json_text import parse_json_text
from .models import (
    ANALYSING,
    BS_COMPLETE,
    BS_FAILED,
    BS_QUALIFYING,
    BS_RESEARCHING,
    BS_SYNTHESISING,
    COMPLETE,
    GATHERING,
    RUN_COMPLETED,
    RUN_TERMINAL,
    BrainstormOpportunity,
    BrainstormSession,
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


class AgentConfigMissingError(IdeationError):
    """The analyst role has no configured row and seeding has not run.

    The plugin guarantees a row exists at startup via seeding (both app.py and
    admin_app.py run it, insert-if-absent, on every cold start — issue #93). A
    missing row at request time means startup seeding failed or was skipped
    entirely; the fallback to ``ANALYST_INSTRUCTIONS`` is deliberately gone, so
    this is raised instead of silently reading the built-in constant.

    There is no challenger equivalent of this class. A missing challenger row
    is not this plugin's fallback to remove — Core's chat-turn spine resolves
    the challenger server-side (``chat_agents_dynamic: true``) and already has
    nothing to fall back to when the row is absent: it 404s the chat turn on
    its own. This error exists only for the one role whose fallback lived in
    this plugin's own code.
    """

    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(
            f"Agent role '{role}' has no configured row. "
            "Seeding may not have run at startup, or Core was unavailable. "
            "Check the app logs and restart the plugin."
        )


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
            try:
                data = parse_json_text(arguments)
                return Report.model_validate(data)
            except (json.JSONDecodeError, ValidationError, RecursionError) as exc:
                raise MalformedReportError(str(exc)) from exc
    raise MalformedReportError(f"the analysis run produced no {REPORT_TOOL_NAME} tool call")


class IdeationService:
    def __init__(
        self,
        core: CoreGateway,
        *,
        min_turns: int = MIN_TURNS,
        max_turns: int = MAX_TURNS,
    ) -> None:
        # There is deliberately no chat_model and no analysis_model either now.
        # The challenger's model comes from its stored chat-agent row, resolved
        # by Core (issue #68); holding one here only ever produced an argument
        # the adapter discarded. The analyst's used to be a genuine fallback
        # held here, but issue #93 removed it: finalise() now requires a
        # stored row and raises AgentConfigMissingError otherwise, so a value
        # held here would be exactly the same dead argument the challenger's
        # already taught this class not to carry.
        self._core = core
        self._min_turns = min_turns
        self._max_turns = max_turns

    async def start_session(
        self,
        *,
        owner_sub: str,
        seed_idea: str,
        challenger_agent_key: str | None = None,
        owner_email: str | None = None,
    ) -> Session:
        """Open a session for a founder's idea, in the gathering phase, with a
        fresh run thread to carry the conversation. The idea itself is not put in
        the challenger's system prompt — it is untrusted, and enters the thread as
        the first fenced user turn (the caller's first :meth:`chat_turn`).

        ``challenger_agent_key`` is pinned on the session at creation (not
        re-resolved later) — an admin editing or deactivating an agent must
        never change the behavior of a session already in flight. Defaults to
        the built-in seed challenger for a founder who didn't pick one."""
        return await self._core.create_session(
            owner_sub=owner_sub,
            seed_idea=seed_idea.strip(),
            thread_id=str(uuid.uuid4()),
            challenger_agent_key=challenger_agent_key or CHALLENGER_AGENT_NAME,
            owner_email=owner_email,
        )

    async def list_active_challengers(self) -> list[dict[str, Any]]:
        """The active challenger roster for a founder's seed-view picker —
        agent_key/agent_name only, never system_prompt (ADR-0016 §1)."""
        rows = await self._core.list_active_agents(role="challenger")
        return [{"agent_key": r["agent_key"], "agent_name": r["agent_name"]} for r in rows]

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

    async def get_messages(self, *, owner_sub: str, session_id: str) -> list[dict[str, str]]:
        """The visible transcript of the founder's own session."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.thread_id is None:
            return []
        return visible_turns(await self._core.get_thread_messages(thread_id=session.thread_id))

    async def list_sessions(self, *, owner_sub: str) -> list[Session]:
        """The founder's sessions, most-recent-first. Soft-deleted sessions are excluded."""
        sessions = await self._core.list_sessions(owner_sub=owner_sub)
        return sorted(
            (s for s in sessions if not s.deleted), key=lambda s: s.created_at or "", reverse=True
        )

    async def get_submitted_idea(self, *, owner_sub: str) -> str | None:
        """The founder's own early-access idea submission, if any — used to prefill
        the seed-idea textbox. ``None`` if they never submitted one via sign-up."""
        return await self._core.get_submitted_idea(owner_sub=owner_sub)

    async def chat_turn(self, *, owner_sub: str, session_id: str, user_message: str) -> TurnResult:
        """Run one buffered challenger turn and return the reply.

        The plugin only decides *whether* the turn may run (gathering, under the
        cap) and *which agent* drives it (the session's own pinned
        ``challenger_agent_key`` — chosen by the founder at session start, or
        the built-in default) — it hands Core the founder's raw message and
        lets the trusted spine fence it, assemble the context, invoke the
        runtime, and persist the turn (ADR-0016 §7). Then it advances the turn
        counter.

        No prompt and no model are passed. Core's chat-turn spine resolves both
        server-side from ``agent_name``, and with ``chat_agents_dynamic: true``
        that is the stored chat-agent row (ADR-0016 §1). This call used to send
        ``CHALLENGER_INSTRUCTIONS`` and a chat model that the adapter dropped on
        the floor (issue #68) — which made the challenger look like it ran on a
        plugin-side constant with its stored row inert, the opposite of the
        truth. Unlike the analyst below, which does send its whole definition
        inline, there is nothing for this path to configure.
        """
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != GATHERING:
            raise NotGatheringError(session.status)
        if session.turn_count >= self._max_turns:
            raise TurnLimitReachedError(self._max_turns)

        result = await self._core.run_chat_turn(
            thread_id=session.thread_id,
            owner_sub=owner_sub,
            agent_name=session.challenger_agent_key,
            user_text=user_message,
        )
        await self._core.set_turn_count(session_id=session_id, turn_count=session.turn_count + 1)
        return result

    async def finalise(self, *, owner_sub: str, session_id: str) -> str:
        """Kick the async analysis run over the whole conversation and move the
        session to ``analysing``. Returns the run id the caller can poll on. Core
        assembles the analyst's context from the thread — the seed idea is already
        its first turn — so nothing is re-passed here.

        The analyst's prompt/model are read live from the admin-configured
        "analyst" role (ADR-0009 internal plugin-config read) — REQUIRED, no
        fallback (issue #93). Both plugin apps seed this row at every cold
        start (insert-if-absent), so a missing row here means seeding failed or
        was skipped, and :class:`AgentConfigMissingError` says so by name
        instead of silently reading ``ANALYST_INSTRUCTIONS``. Unlike the
        challenger (resolved server-side by Core's chat-agent registry), the
        analyst sends its whole definition inline on every call, so this
        plugin's own code is what has to look the live config up."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != GATHERING:
            raise NotGatheringError(session.status)
        if session.turn_count < self._min_turns:
            raise NotEnoughTurnsError(session.turn_count)

        analyst_config = await self._core.get_own_config(role="analyst")
        if analyst_config is None:
            raise AgentConfigMissingError("analyst")

        run_id = await self._core.request_analysis(
            thread_id=session.thread_id,
            owner_sub=owner_sub,
            agent_name=ANALYST_AGENT_NAME,
            definition=analyst_definition(
                model=analyst_config["model"], instructions=analyst_config["system_prompt"]
            ),
            output_tool=report_tool_schema(),
        )
        await self._core.set_status(session_id=session_id, status=ANALYSING, analysis_run_id=run_id)
        return run_id

    async def delete_session(self, *, owner_sub: str, session_id: str) -> None:
        """Soft-delete a session — deletable from any status (gathering,
        analysing, or complete); no state-machine restriction, unlike chat_turn
        or finalise. Raises SessionNotFoundError if missing or not owned by this
        founder (the same ownership guard every other mutation already uses)."""
        await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        await self._core.delete_session(session_id=session_id)

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


class MalformedOpportunitiesError(IdeationError):
    """The synthesis run finished without a valid structured shortlist. Caught by
    the service and recorded as a failed *session*, not raised to the caller."""


class MalformedFindingsError(IdeationError):
    """A research run finished without a valid findings call. Reported as that
    angle's status, never raised to the caller."""


def visible_turns(
    raw: list[dict[str, Any]], *, strip_brief_state: bool = False
) -> list[dict[str, str]]:
    """The user/assistant turns of a stored thread that a founder saw: tool,
    system and empty messages are dropped, and (Brain-Storm) the hidden
    ``<brief_state>`` block is stripped exactly as live replies are."""
    turns: list[dict[str, str]] = []
    for m in raw:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        if role == "assistant" and strip_brief_state:
            content, _ = parse_brief_state(content)
        if not content.strip():
            continue
        turns.append({"role": role, "content": content})
    return turns


def extract_opportunities(run_messages: list[dict[str, Any]]) -> OpportunitySet:
    """Pull the ranked shortlist out of the synthesis run's transcript (the last
    call to the output tool — a retried malformed call supersedes the earlier one).
    Raises :class:`MalformedOpportunitiesError` if missing or invalid."""
    found: Any = None
    for message in run_messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") != OPPORTUNITIES_TOOL_NAME:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    found = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            else:
                found = arguments
    if found is None:
        raise MalformedOpportunitiesError(
            f"the synthesis run produced no {OPPORTUNITIES_TOOL_NAME} tool call"
        )
    try:
        return OpportunitySet.model_validate(found)
    except ValidationError as exc:
        raise MalformedOpportunitiesError(str(exc)) from exc


def extract_findings(run_messages: list[dict[str, Any]]) -> FindingSet:
    """Pull one research agent's findings out of its run transcript (the last
    call to the findings tool). Raises :class:`MalformedFindingsError` if
    missing or invalid."""
    found: Any = None
    for message in run_messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") != FINDINGS_TOOL_NAME:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    found = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            else:
                found = arguments
    if found is None:
        raise MalformedFindingsError(f"the run produced no {FINDINGS_TOOL_NAME} tool call")
    try:
        return FindingSet.model_validate(found)
    except ValidationError as exc:
        raise MalformedFindingsError(str(exc)) from exc


class BrainstormService:
    """The Brain-Storming qualifying chat — transport-agnostic, like
    :class:`IdeationService`. Sessions start in ``qualifying``; each turn is a
    buffered chat turn with the qualifier agent, capped at
    its own safety ceiling ``QUALIFIER_MAX_TURNS`` (not Pressure Test's)."""

    def __init__(self, core: CoreGateway, *, max_turns: int = QUALIFIER_MAX_TURNS) -> None:
        self._core = core
        self._max_turns = max_turns

    async def start_session(
        self,
        *,
        owner_sub: str,
        target: str | None = None,
        geography: str | None = None,
        problem: str | None = None,
        title: str | None = None,
        owner_email: str | None = None,
    ) -> BrainstormSession:
        def clean(v: str | None) -> str | None:
            return (v or "").strip() or None

        return await self._core.create_brainstorm_session(
            owner_sub=owner_sub,
            target=clean(target),
            geography=clean(geography),
            problem=clean(problem),
            thread_id=str(uuid.uuid4()),
            title=clean(title),
            owner_email=clean(owner_email),
        )

    async def _load_owned(self, *, owner_sub: str, session_id: str) -> BrainstormSession:
        session = await self._core.get_brainstorm_session(
            owner_sub=owner_sub, session_id=session_id
        )
        if session is None or session.deleted:
            raise SessionNotFoundError(session_id)
        return session

    async def get_session(self, *, owner_sub: str, session_id: str) -> BrainstormSession:
        """The session's current state, advancing the state machine if the agent
        runs it is waiting on have finished. Safe to poll repeatedly."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status == BS_RESEARCHING:
            return await self._advance_research(session)
        if session.status == BS_SYNTHESISING:
            return await self._advance_synthesis(session)
        return session

    async def list_opportunities(
        self, *, owner_sub: str, session_id: str
    ) -> list[BrainstormOpportunity]:
        """The session's ranked opportunities (empty until it is complete)."""
        await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        return await self._core.list_brainstorm_opportunities(
            owner_sub=owner_sub, session_id=session_id
        )

    async def get_research(self, *, owner_sub: str, session_id: str) -> list[dict[str, Any]]:
        """One entry per research angle: its status (``succeeded``, ``failed``,
        ``malformed``, ``never_started`` or ``running``) and its findings (empty
        unless it succeeded). An angle is never left out."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.research_findings is not None:
            return list(session.research_findings)
        return await self._read_research(session)

    async def _read_research(self, session: BrainstormSession) -> list[dict[str, Any]]:
        """Read each angle's findings back from its research run."""
        run_ids = list(session.research_run_ids or [])
        out: list[dict[str, Any]] = []
        for i, agent_name in enumerate(RESEARCH_AGENT_NAMES):
            angle = agent_name.removeprefix("ideation-brainstorm-")
            status = "never_started"
            findings: list[dict[str, Any]] = []
            run_id = run_ids[i] if i < len(run_ids) else None
            view = await self._core.get_agent_run(run_id=run_id) if run_id else None
            if view is not None:
                if not view.is_terminal:
                    status = "running"
                elif view.never_started:
                    status = "never_started"
                elif not view.succeeded:
                    status = "failed"
                else:
                    try:
                        fs = extract_findings(view.messages)
                        status = "succeeded"
                        findings = [f.model_dump() for f in fs.findings]
                    except MalformedFindingsError:
                        status = "malformed"
            out.append({"angle": angle, "status": status, "findings": findings})
        return out

    async def _store_research(self, session: BrainstormSession) -> BrainstormSession:
        """Persist the extracted findings with the session once every research
        run is terminal, so they no longer depend on the runs' retention."""
        research = await self._read_research(session)
        if any(r["status"] == "running" for r in research):
            return session
        await self._core.update_brainstorm_session(
            session_id=session.id, research_findings=research
        )
        return dataclasses.replace(session, research_findings=research)

    async def get_messages(self, *, owner_sub: str, session_id: str) -> list[dict[str, str]]:
        """The visible transcript of the founder's own brain-storm, with the
        ``<brief_state>`` block stripped from assistant turns."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.thread_id is None:
            return []
        raw = await self._core.get_thread_messages(thread_id=session.thread_id)
        return visible_turns(raw, strip_brief_state=True)

    async def list_sessions(self, *, owner_sub: str) -> list[BrainstormSession]:
        """The founder's sessions, most-recent-first, soft-deleted excluded."""
        sessions = await self._core.list_brainstorm_sessions(owner_sub=owner_sub)
        return sorted(
            (s for s in sessions if not s.deleted), key=lambda s: s.created_at or "", reverse=True
        )

    async def chat_turn(self, *, owner_sub: str, session_id: str, user_message: str) -> TurnResult:
        """Run one buffered qualifier turn, then advance the turn counter."""
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != BS_QUALIFYING or session.thread_id is None:
            raise NotGatheringError(session.status)
        if session.turn_count >= self._max_turns:
            raise TurnLimitReachedError(self._max_turns)

        result = await self._core.run_chat_turn(
            thread_id=session.thread_id,
            owner_sub=owner_sub,
            agent_name=QUALIFIER_AGENT_NAME,
            user_text=user_message,
        )
        # The readiness signal is the structured block, parsed and validated —
        # never the prose. The latest valid block wins; an absent or malformed one
        # leaves the previous brief untouched. The block is hidden from the founder.
        visible, state = parse_brief_state(result.reply)
        fields: dict[str, Any] = {"turn_count": session.turn_count + 1}
        if state is not None:
            fields["brief"] = state.model_dump()
        await self._core.update_brainstorm_session(session_id=session_id, **fields)
        return dataclasses.replace(result, reply=visible)

    async def delete_session(self, *, owner_sub: str, session_id: str) -> None:
        await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        await self._core.delete_brainstorm_session(session_id=session_id)

    # ── Research fan-out ─────────────────────────────────────────────────────

    async def finalise(self, *, owner_sub: str, session_id: str) -> BrainstormSession:
        """Fire all six research agents under one causation chain and move the
        session to ``researching``.

        The shared ``chain_id`` is what makes them siblings the orchestration
        engine's ``agent_fan_in`` recognises as a set; six uncorrelated runs would
        each be a chain root and the join would never fire. Each agent's prompt and
        model are read live from its seeded config row — required, no fallback.
        """
        session = await self._load_owned(owner_sub=owner_sub, session_id=session_id)
        if session.status != BS_QUALIFYING:
            raise NotGatheringError(session.status)

        brief: dict[str, Any] = {
            "target": session.target,
            "geography": session.geography,
            "problem": session.problem,
        }
        if session.brief:
            brief["qualified_brief"] = session.brief

        chain_id = str(uuid.uuid4())
        # Resolve every config before firing any run, so a missing row cannot
        # leave earlier agents' runs orphaned (and billed).
        configs: dict[str, dict[str, Any]] = {}
        for agent_name in RESEARCH_AGENT_NAMES:
            config = await self._core.get_own_config(role=agent_name)
            if config is None:
                raise AgentConfigMissingError(agent_name)
            configs[agent_name] = config
        research_run_ids: list[str] = []
        for agent_name in RESEARCH_AGENT_NAMES:
            config = configs[agent_name]
            research_run_ids.append(
                await self._core.request_agent_run(
                    agent_name=agent_name,
                    definition=research_definition(
                        model=config["model"], instructions=config["system_prompt"]
                    ),
                    output_tool=findings_tool_schema(),
                    input_payload={"brief": brief},
                    causation_id=chain_id,
                )
            )
        await self._core.update_brainstorm_session(
            session_id=session_id,
            status=BS_RESEARCHING,
            chain_id=chain_id,
            research_run_ids=research_run_ids,
        )
        return dataclasses.replace(
            session,
            status=BS_RESEARCHING,
            chain_id=chain_id,
            research_run_ids=research_run_ids,
        )

    # ── State transitions ────────────────────────────────────────────────────

    #: Shown when an agent run was never claimed by a runtime rather than having
    #: run and gone wrong — an infrastructure fault a retry usually fixes.
    NEVER_STARTED_REASON = (
        "This brain-storm never started — the work was queued but nothing picked it up, "
        "so no research ran and nothing was charged for it. This is a fault on our "
        "side, not with what you asked for. Running it again usually works."
    )

    async def _advance_research(self, session: BrainstormSession) -> BrainstormSession:
        """Research -> synthesis, once the engine has fired the synthesis run.

        The orchestration engine watches the research set and fires synthesis
        itself; this only discovers that run (nothing tells the plugin its id) and
        records it. A research set that failed outright never produces a synthesis
        run, so that case is detected here rather than left to hang.
        """
        if session.chain_id is None:  # pragma: no cover — researching implies a chain
            return session
        synthesis = await self._core.find_chain_run(
            chain_id=session.chain_id, agent_name=SYNTHESIS_AGENT_NAME
        )
        if synthesis is not None:
            session = await self._store_research(session)
            await self._core.update_brainstorm_session(
                session_id=session.id, status=BS_SYNTHESISING, synthesis_run_id=synthesis.id
            )
            return dataclasses.replace(
                session, status=BS_SYNTHESISING, synthesis_run_id=synthesis.id
            )

        views = [await self._core.get_agent_run(run_id=rid) for rid in session.research_run_ids]
        if any(v is not None and not v.is_terminal for v in views):
            return session  # still researching
        if any(v is not None and v.succeeded for v in views):
            # Terminal with at least one success: the engine is entitled to a
            # moment to react to the completion event — don't race it to a
            # false failure.
            return session
        session = await self._store_research(session)
        if views and all(v is not None and v.never_started for v in views):
            return await self._fail(session, self.NEVER_STARTED_REASON)
        return await self._fail(
            session,
            "Every research agent failed to return usable findings. "
            "Nothing was found to build opportunities from — try running again.",
        )

    async def _advance_synthesis(self, session: BrainstormSession) -> BrainstormSession:
        """Synthesis -> complete, storing the ranked opportunities."""
        if session.synthesis_run_id is None:  # pragma: no cover — guarded by the caller
            return session
        view = await self._core.get_agent_run(run_id=session.synthesis_run_id)
        if view is not None and not view.is_terminal:
            return session  # still synthesising
        if view is not None and view.never_started:
            return await self._fail(session, self.NEVER_STARTED_REASON)
        if view is None or not view.succeeded:
            return await self._fail(
                session, "The analysis that ranks the opportunities failed. Try running again."
            )
        try:
            opportunity_set = extract_opportunities(view.messages)
        except MalformedOpportunitiesError:
            return await self._fail(
                session, "The analysis finished but returned nothing usable. Try running again."
            )

        # Trim rather than reject: an over-long list is the model ignoring its
        # brief, and the extras are the ones it ranked lowest.
        opportunities = [
            {
                "title": o.title,
                "pitch": o.pitch,
                "rationale": o.rationale,
                "evidence": [src.model_dump() for src in o.sources],
            }
            for o in opportunity_set.opportunities
        ][:MAX_OPPORTUNITIES]
        if not opportunities:
            return await self._fail(
                session, "The analysis returned no opportunities at all. Try running again."
            )

        await self._core.save_brainstorm_opportunities(
            session_id=session.id, opportunities=opportunities, model=view.model
        )
        await self._core.update_brainstorm_session(session_id=session.id, status=BS_COMPLETE)
        return dataclasses.replace(session, status=BS_COMPLETE)

    async def _fail(self, session: BrainstormSession, reason: str) -> BrainstormSession:
        await self._core.update_brainstorm_session(
            session_id=session.id, status=BS_FAILED, failure_reason=reason
        )
        return dataclasses.replace(session, status=BS_FAILED, failure_reason=reason)
