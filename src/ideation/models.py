"""Plain data types the orchestration works in — no I/O, no framework."""

from __future__ import annotations

from dataclasses import dataclass

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
