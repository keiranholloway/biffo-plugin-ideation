"""Plain data types the orchestration works in — no I/O, no framework."""

from __future__ import annotations

from dataclasses import dataclass

# Session lifecycle.
GATHERING = "gathering"  # the requirement-gathering chat is in progress
ANALYSING = "analysing"  # finalised; the async analysis run is in flight
COMPLETE = "complete"  # the report is ready
STATUSES = frozenset({GATHERING, ANALYSING, COMPLETE})


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
