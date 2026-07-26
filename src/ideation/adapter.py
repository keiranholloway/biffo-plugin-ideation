"""The HTTP ``CoreGateway`` — binds the orchestration's port to Core's seams.

This is the adapter side of the hexagon: it translates each :class:`CoreGateway`
method into a call to a Core endpoint the platform now provides, and parses the
response back into a domain object. It is deliberately **pure** — it takes a
``Transport`` and does no signing, HTTP, or AWS itself — so the mapping is fully
testable with a fake transport. The real transport (SigV4 for the service
principal + the founder's ``X-Biffo-User-Token``) is wired in the plugin's Lambda
(ADR-0017 §3/§5); it is the only piece that touches the network.

Seam mapping (all under ``/api/v1``):

- session/report rows → ``/internal/owner-data/<table>`` (ADR-0017 §5). The owner
  is stamped by Core from the forwarded token, so ``owner_sub`` is **never** sent
  in a body/param; the adapter relies on Core's owner-scoping and ignores the
  ``owner_sub`` the port passes (a non-HTTP adapter/fake uses it instead).
- a challenger turn → ``/internal/agent-chat/{agent_key}`` (ADR-0017 §3). Core
  resolves the registered agent by key, so ``system_prompt``/``model`` from the
  port are not sent — the registration is the trusted source (ADR-0016 §1).
- the async analysis → read the thread's conversation, then create an agent run
  carrying the analyst definition + the report *output tool* (ADR-0017 §4).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from .models import GATHERING, Run, Session, TurnResult

_ROOT = "/api/v1/internal"
_SESSIONS = f"{_ROOT}/owner-data/ideation_sessions"
_REPORTS = f"{_ROOT}/owner-data/ideation_reports"
_AGENT_CHAT = f"{_ROOT}/agent-chat"
_AGENT_RUNS = f"{_ROOT}/agent-runs"
_IDEA_SUBMISSIONS = f"{_ROOT}/idea-submissions/mine"


class CoreHttpError(Exception):
    """A Core call failed (non-2xx other than the not-found the adapter handles)."""


class CoreNotFoundError(CoreHttpError):
    """A Core call returned 404 — mapped to ``None`` for the owner-scoped reads."""


class Transport(Protocol):
    """The one network boundary. An implementation SigV4-signs the request as the
    plugin's service principal and forwards the founder's Cognito token; it returns
    the parsed JSON body on 2xx, raises :class:`CoreNotFoundError` on 404, and
    :class:`CoreHttpError` on any other non-2xx."""

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any: ...


def _load_json_column(value: Any) -> Any:
    """Parse a Text column that holds JSON. Tolerates a dict (already parsed by a
    JSON-typed transport) and None (returns None), so the caller need not care how
    the value arrived."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def _session_from_row(row: dict[str, Any]) -> Session:
    """Map an ``ideation_sessions`` owner-data row to a :class:`Session`."""
    return Session(
        id=row["id"],
        owner_sub=row["owner_sub"],
        seed_idea=row["seed_idea"],
        status=row["status"],
        thread_id=row["thread_id"],
        turn_count=row.get("turn_count") or 0,
        analysis_run_id=row.get("analysis_run_id"),
        title=row.get("title"),
        created_at=row.get("created_at"),
    )


class CoreHttpGateway:
    """A :class:`~ideation.ports.CoreGateway` backed by Core's HTTP seams."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    async def create_session(self, *, owner_sub: str, seed_idea: str, thread_id: str) -> Session:
        row = await self._t.request(
            "POST",
            _SESSIONS,
            json={
                "seed_idea": seed_idea,
                "thread_id": thread_id,
                "status": GATHERING,
                "turn_count": 0,
            },
        )
        return _session_from_row(row)

    async def get_session(self, *, owner_sub: str, session_id: str) -> Session | None:
        try:
            row = await self._t.request("GET", f"{_SESSIONS}/{session_id}")
        except CoreNotFoundError:
            return None
        return _session_from_row(row)

    async def list_sessions(self, *, owner_sub: str) -> list[Session]:
        # No params: Core's owner-data list route already scopes to the caller
        # via the forwarded token, so nothing further is filtered here.
        rows = await self._t.request("GET", _SESSIONS)
        return [_session_from_row(row) for row in rows]

    async def set_turn_count(self, *, session_id: str, turn_count: int) -> None:
        await self._t.request("PATCH", f"{_SESSIONS}/{session_id}", json={"turn_count": turn_count})

    async def set_status(
        self, *, session_id: str, status: str, analysis_run_id: str | None = None
    ) -> None:
        body: dict[str, Any] = {"status": status}
        if analysis_run_id is not None:
            body["analysis_run_id"] = analysis_run_id
        await self._t.request("PATCH", f"{_SESSIONS}/{session_id}", json=body)

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
        # agent_name is the registered agent key; system_prompt/model come from the
        # registration in Core, not from here.
        resp = await self._t.request(
            "POST",
            f"{_AGENT_CHAT}/{agent_name}",
            json={"message": user_text, "thread_id": thread_id},
        )
        return TurnResult(
            reply=resp["reply"],
            model=resp.get("model"),
            finish_reason=resp.get("finish_reason"),
            input_tokens=resp.get("input_tokens"),
            output_tokens=resp.get("output_tokens"),
            cost_usd=resp.get("cost_usd"),
        )

    async def request_analysis(
        self,
        *,
        thread_id: str,
        owner_sub: str,
        agent_name: str,
        definition: dict[str, Any],
        output_tool: dict[str, Any],
    ) -> str:
        # The async run builds from input_payload (not a thread), so hand it the
        # conversation. The report tool is an OUTPUT tool, offered via output_tools.
        conversation = await self._t.request("GET", f"{_AGENT_RUNS}/threads/{thread_id}/messages")
        snapshot = {**definition, "output_tools": [output_tool]}
        run = await self._t.request(
            "POST",
            _AGENT_RUNS,
            json={
                "agent_name": agent_name,
                "definition_snapshot": snapshot,
                "input_payload": {"conversation": conversation.get("messages", [])},
                "thread_id": thread_id,
            },
        )
        return run["id"]

    async def get_run(self, *, run_id: str) -> Run | None:
        try:
            run = await self._t.request("GET", f"{_AGENT_RUNS}/{run_id}")
        except CoreNotFoundError:
            return None
        result = run.get("result") or {}
        model = result.get("model") or (run.get("definition_snapshot") or {}).get("model")
        return Run(
            id=run["id"],
            status=run["status"],
            messages=run.get("messages") or [],
            model=model,
        )

    async def save_report(
        self,
        *,
        session_id: str,
        prd: dict[str, Any],
        scorecard: dict[str, Any],
        model: str | None,
    ) -> None:
        # prd/scorecard are stored in Text columns (Core's plugin-table type map
        # has no JSON type — an unknown type silently falls back to String, which
        # would truncate the report), so they are JSON-serialised here and parsed
        # back in get_report. Core stores/returns the string verbatim.
        await self._t.request(
            "POST",
            _REPORTS,
            json={
                "session_id": session_id,
                "prd": json.dumps(prd),
                "scorecard": json.dumps(scorecard),
                "model": model,
            },
        )

    async def get_report(self, *, session_id: str) -> dict[str, Any] | None:
        rows = await self._t.request("GET", _REPORTS, params={"session_id": session_id})
        if not rows:
            return None
        row = rows[0]
        return {
            "prd": _load_json_column(row.get("prd")),
            "scorecard": _load_json_column(row.get("scorecard")),
            "model": row.get("model"),
        }

    async def get_submitted_idea(self, *, owner_sub: str) -> str | None:
        try:
            row = await self._t.request("GET", _IDEA_SUBMISSIONS)
        except CoreNotFoundError:
            return None
        return row["idea"]
