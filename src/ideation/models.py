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
class Usage:
    """The completed-turn accounting a streamed LLM call reports on its final
    chunk — mirrors the runtime's ``LLMResponse`` (ADR-0016 §4)."""

    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class StreamChunk:
    """One event from a streamed turn: a text ``delta`` as it arrives, or — on the
    final chunk — the completed ``Usage``. Structurally matches the runtime's
    ``StreamChunk`` so the adapter passes them straight through."""

    delta: str = ""
    done: Usage | None = None
