"""Plain data types the orchestration works in — no I/O, no framework."""

from __future__ import annotations

from dataclasses import dataclass, field

from .definitions import CHALLENGER_AGENT_NAME

# Session lifecycle.
GATHERING = "gathering"  # the requirement-gathering chat is in progress
ANALYSING = "analysing"  # finalised; the async analysis run is in flight
COMPLETE = "complete"  # the report is ready
STATUSES = frozenset({GATHERING, ANALYSING, COMPLETE})

# Terminal states of the async analysis run (Core's AgentRun, ADR-0014). Read when
# a founder polls: a completed run is materialised into the report, a failed one is
# surfaced as an error.
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_TERMINAL = frozenset({RUN_COMPLETED, RUN_FAILED})


@dataclass(frozen=True)
class Session:
    """An ideation session — one idea being explored by one founder."""

    id: str
    owner_sub: str
    seed_idea: str
    status: str
    thread_id: str
    turn_count: int
    analysis_run_id: str | None = None
    title: str | None = None
    created_at: str | None = None
    deleted: bool = False
    #: Which challenger persona this session was started with — pinned at
    #: creation so an admin editing/deactivating an agent never changes the
    #: behavior of a session already in flight. Defaults to the built-in seed
    #: challenger for a founder who didn't pick one from the active roster.
    challenger_agent_key: str = CHALLENGER_AGENT_NAME


@dataclass(frozen=True)
class Run:
    """A read of the async analysis run (Core's AgentRun) — just what the plugin
    needs to materialise the report: its terminal status, the transcript to extract
    the ``submit_ideation_report`` tool call from, and the model that produced it."""

    id: str
    status: str
    messages: list[dict[str, object]]
    model: str | None = None


@dataclass(frozen=True)
class TurnResult:
    """One buffered challenger turn's reply. The spine (ADR-0016, *buffered*
    amendment) returns the whole assistant message at once — Core assembles the
    context, synchronously invokes the runtime, and hands back the finished reply
    plus its accounting. Mirrors the spine's ``ChatTurnResult`` so the adapter
    passes it straight through."""

    reply: str
    model: str | None = None
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


# Brain-Storming session lifecycle.
BS_QUALIFYING = "qualifying"  # the qualifying chat is in progress
BS_RESEARCHING = "researching"  # the parallel research agents are running
BS_SYNTHESISING = "synthesising"  # the synthesis agent is reconciling findings
BS_COMPLETE = "complete"  # ranked opportunities are stored
BS_FAILED = "failed"
BRAINSTORM_STATUSES = frozenset(
    {BS_QUALIFYING, BS_RESEARCHING, BS_SYNTHESISING, BS_COMPLETE, BS_FAILED}
)

# Agent-run status values (Core's AgentRun) — ``RUN_COMPLETED``/``RUN_FAILED``
# above are the terminal ones; a run is terminal when in ``RUN_TERMINAL``.


@dataclass(frozen=True)
class AgentRunView:
    """A read of an async agent run (Core's AgentRun) — just what the plugin
    needs to decide whether it is done and to extract its output-tool call."""

    id: str
    status: str
    messages: list[dict[str, object]] = field(default_factory=list)
    model: str | None = None
    #: When a runtime claimed this run. None means nothing ever picked it up.
    started_at: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in RUN_TERMINAL

    @property
    def succeeded(self) -> bool:
        return self.status == RUN_COMPLETED

    @property
    def never_started(self) -> bool:
        """Terminal, unsuccessful, and never claimed by a runtime.

        A run reaches ``running`` only by being claimed, so ``started_at`` is the
        structural signal that nothing ever picked it up. Deliberately not a
        substring match on Core's error text, which is prose that can be reworded.
        """
        return self.is_terminal and not self.succeeded and self.started_at is None


@dataclass(frozen=True)
class BrainstormSession:
    """A Brain-Storming session — one qualified brief researched by parallel agents."""

    id: str
    owner_sub: str
    status: str
    title: str | None = None
    target: str | None = None
    geography: str | None = None
    problem: str | None = None
    brief: dict[str, object] | None = None
    thread_id: str | None = None
    turn_count: int = 0
    chain_id: str | None = None
    research_run_ids: list[str] = field(default_factory=list)
    synthesis_run_id: str | None = None
    failure_reason: str | None = None
    created_at: str | None = None
    deleted: bool = False

    @property
    def ready(self) -> bool:
        """True only when the qualifier's structured signal said the brief is ready."""
        return bool(self.brief and self.brief.get("ready") is True)

    @property
    def gaps(self) -> list[str]:
        raw = (self.brief or {}).get("gaps")
        return [str(g) for g in raw] if isinstance(raw, list) else []


@dataclass(frozen=True)
class BrainstormOpportunity:
    """One ranked business opportunity a Brain-Storming session produced."""

    id: str
    owner_sub: str
    session_id: str
    rank: int
    title: str
    pitch: str
    rationale: str | None = None
    evidence: object | None = None
    model: str | None = None
