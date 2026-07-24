"""The boundary the orchestration depends on (a hexagonal port).

The real adapter binds this to Core's buffered chat spine (ADR-0016, *buffered*
amendment) and Core's API (ADR-0002 — never the DB). The tests bind it to a fake.
Keeping the logic behind this interface is what lets the orchestration be built
and tested now; the deferred piece is Core generalising #497's prompt-assistant
spine into a reusable, founder-gated capability a plugin can drive, plus the thin
adapter that calls it.

There is deliberately no ``Streamer`` port any more. Under the buffered amendment
the runtime does not stream: Core assembles the turn, synchronously invokes the
runtime, and returns the whole reply. So a chat turn is one call
(:meth:`run_chat_turn`), not a stream — and the security-critical assembly
(fencing the founder's untrusted message, bounding history, the trusted system
prompt) stays inside Core's trusted layer, never in this plugin.
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import Run, Session, TurnResult


class CoreGateway(Protocol):
    """Everything the orchestration needs from Core, all via the API/spine
    (ADR-0002 — the plugin never touches the database).

    Session/report rows live in the ``ideation_*`` tables the module declared;
    the chat transcript lives as a thread of agent runs (ADR-0016 §2). The real
    adapter reaches these under the founder's authority; ownership is enforced by
    passing ``owner_sub`` on every read.
    """

    async def create_session(
        self, *, owner_sub: str, seed_idea: str, thread_id: str
    ) -> Session: ...

    async def get_session(self, *, owner_sub: str, session_id: str) -> Session | None: ...

    async def set_turn_count(self, *, session_id: str, turn_count: int) -> None: ...

    async def set_status(
        self, *, session_id: str, status: str, analysis_run_id: str | None = None
    ) -> None: ...

    async def run_chat_turn(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        agent_name: str,
        system_prompt: str,
        user_text: str,
        model: str,
    ) -> TurnResult:
        """Run one buffered challenger turn through the spine and return the reply.

        Core does the trusted work: it fences ``user_text`` as untrusted data,
        prepends the trusted ``system_prompt``, replays the thread's bounded
        history, synchronously invokes the runtime, and persists the exchange as a
        run in the thread (ADR-0016 §2, §7). The plugin passes its domain prompt
        and the founder's *raw* message — it must never fence or assemble itself,
        so the security guarantee lives in one trusted place.
        """
        ...

    async def request_analysis(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        agent_name: str,
        definition: dict[str, Any],
        output_tool: dict[str, Any],
    ) -> str:
        """Kick the async analysis run over the thread; returns its run id. Core
        assembles the analyst's context from the thread (which already holds the
        seed idea as its first turn) and registers the plugin-provided
        ``output_tool`` schema for the run's structured result."""
        ...

    async def get_run(self, *, run_id: str) -> Run | None:
        """Read the async analysis run (Core's AgentRun). Used when a founder polls
        for their report: a terminal run is materialised into the stored report
        under the founder's own request (the chosen §5 trust model has no
        event-subscriber write path)."""
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
