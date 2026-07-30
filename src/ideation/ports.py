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
        self, *, owner_sub: str, seed_idea: str, thread_id: str, challenger_agent_key: str
    ) -> Session: ...

    async def get_session(self, *, owner_sub: str, session_id: str) -> Session | None: ...

    async def list_sessions(self, *, owner_sub: str) -> list[Session]:
        """Every session owned by this founder, in no particular order — the
        caller sorts. Core's owner-scoped list route already restricts rows to
        the caller (ADR-0017 §5); ``owner_sub`` is accepted here for parity
        with the rest of this port and used by non-HTTP adapters/fakes."""
        ...

    async def set_turn_count(self, *, session_id: str, turn_count: int) -> None: ...

    async def set_status(
        self, *, session_id: str, status: str, analysis_run_id: str | None = None
    ) -> None: ...

    async def delete_session(self, *, session_id: str) -> None: ...

    async def run_chat_turn(
        self, *, thread_id: str, owner_sub: str, agent_name: str, user_text: str
    ) -> TurnResult:
        """Run one buffered challenger turn through the spine and return the reply.

        The plugin passes the *agent key* and the founder's **raw** message, and
        nothing else. Core does all the trusted work: it resolves the agent's
        prompt and model from its registration — which with
        ``chat_agents_dynamic: true`` is the stored chat-agent row — fences
        ``user_text`` as untrusted data, replays the thread's bounded history,
        synchronously invokes the runtime, and persists the exchange as a run in
        the thread (ADR-0016 §1, §2, §7). The plugin must never fence or
        assemble, so the security guarantee lives in one trusted place.

        This signature used to take ``system_prompt`` and ``model`` as well.
        Neither was ever sent (issue #68). Two dead arguments are not merely
        untidy: they claimed control this side does not have, and the plain
        reading of the call site — that the challenger runs on a plugin-side
        constant and its stored row is inert — was the wrong diagnosis reached
        while investigating #58 and nearly filed as a bug. Wiring them through
        instead would have *created* that bug, by overriding the stored row that
        the dynamic registry makes authoritative.
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

    async def get_own_config(self, *, role: str) -> dict[str, Any] | None:
        """The live, admin-editable config (system_prompt + model) for one of
        this plugin's own roles, or None if never configured."""
        ...

    async def seed_own_config(self, *, config: list[dict[str, Any]]) -> list[dict[str, bool]]:
        """Seed this plugin's own agent-config rows, insert-if-absent (issue #93).

        Sends a list of role definitions (agent_key, agent_name, role,
        system_prompt, model, required_group, active — the shape
        ``ideation.effective_config.builtin_chat_agents()`` returns). Returns a
        list of ``{"role": str, "created": bool}``, one per definition.

        **Never overwrites an existing row**, regardless of differences between
        the supplied values and what is stored — the property the whole
        seeding guarantee rests on. Called on every cold start (both app.py and
        admin_app.py), so an admin's edited prompt must survive every
        redeploy; overwriting it would silently revert the feature this seam
        exists to protect. Writes no history rows either: a seed-created row is
        the row's origin, not a change to it."""
        ...

    async def list_active_agents(self, *, role: str) -> list[dict[str, Any]]:
        """Every active row for this plugin's own given role (e.g. "challenger")
        — for a founder-facing picker. Each item carries at least agent_key and
        agent_name; callers must not forward system_prompt to a founder-facing
        response (ADR-0016 §1 — never send prompt text to an unprivileged
        caller, even though it's already been read server-side)."""
        ...

    async def get_submitted_idea(self, *, owner_sub: str) -> str | None:
        """The founder's own early-access idea submission, if any (the seed-idea
        prefill source). ``owner_sub`` is accepted for parity with the rest of this
        port and used by non-HTTP adapters/fakes; the real HTTP adapter relies on
        Core's forwarded-token scoping instead."""
        ...
