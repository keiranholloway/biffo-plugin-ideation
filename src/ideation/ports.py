"""The boundaries the orchestration depends on (hexagonal ports).

Real adapters implement these against Core's API (ADR-0002 — never the DB) and
the runtime's streaming client (ADR-0016); the tests implement fakes. Keeping the
logic behind these interfaces is what lets the orchestration be built and tested
now, with only the thin Function-URL / run_as:user adapter deferred until the
spine lands.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from .models import Session, StreamChunk


class Streamer(Protocol):
    """The LLM streaming boundary — implemented by the runtime's
    ``OpenRouterClient.stream`` (ADR-0016 §4)."""

    def stream(
        self, *, model: str, messages: list[dict[str, Any]]
    ) -> AsyncIterator[StreamChunk]: ...


class CoreGateway(Protocol):
    """Everything the orchestration needs from Core, all via the API (ADR-0002).

    Session/report rows live in the ``ideation_*`` tables the module declared;
    the chat transcript lives as a thread of agent runs (ADR-0016 §2). The real
    adapter reaches these through Core's internal API under the founder's
    authority; ownership is enforced by passing ``owner_sub`` on every read.
    """

    async def create_session(
        self, *, owner_sub: str, seed_idea: str, thread_id: str
    ) -> Session: ...

    async def get_session(
        self, *, owner_sub: str, session_id: str
    ) -> Session | None: ...

    async def set_turn_count(self, *, session_id: str, turn_count: int) -> None: ...

    async def set_status(
        self, *, session_id: str, status: str, analysis_run_id: str | None = None
    ) -> None: ...

    async def thread_messages(self, *, thread_id: str) -> list[dict[str, Any]]:
        """The ordered user/assistant history of the session's run thread."""
        ...

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
        """Persist one completed turn as a run in the thread (ADR-0016 §2)."""
        ...

    async def request_analysis(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        definition: dict[str, Any],
        conversation: list[dict[str, Any]],
    ) -> str:
        """Kick the async analysis run; returns its run id."""
        ...

    async def save_report(
        self,
        *,
        session_id: str,
        prd: dict[str, Any],
        scorecard: dict[str, Any],
        model: str | None,
    ) -> None: ...

    async def get_report(self, *, session_id: str) -> dict[str, Any] | None: ...
