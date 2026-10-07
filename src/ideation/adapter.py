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
  resolves the registered agent by key — with ``chat_agents_dynamic: true`` that
  is the stored chat-agent row — so the prompt and model are the registration's,
  never this plugin's (ADR-0016 §1). The port has no parameter for either.
- the async analysis → read the thread's conversation, then create an agent run
  carrying the analyst definition + the report *output tool* (ADR-0017 §4).
- this plugin's own agent config → ``/internal/plugins/me/config`` (ADR-0009):
  ``GET .../{role}`` reads one role live; ``POST .../seed`` (``seed_own_config``)
  seeds both roles insert-if-absent at startup (issue #93) — SigV4-only, no
  forwarded founder token, resolved from the caller's own service identity so
  a plugin can never seed another's config.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from .definitions import CHALLENGER_AGENT_NAME
from .json_text import parse_json_text
from .models import (
    BS_QUALIFYING,
    GATHERING,
    AgentRunView,
    BrainstormOpportunity,
    BrainstormSession,
    Run,
    Session,
    TurnResult,
)

_ROOT = "/api/v1/internal"
_SESSIONS = f"{_ROOT}/owner-data/ideation_sessions"
_REPORTS = f"{_ROOT}/owner-data/ideation_reports"
_BS_SESSIONS = f"{_ROOT}/owner-data/brainstorm_sessions"
_BS_OPPORTUNITIES = f"{_ROOT}/owner-data/brainstorm_opportunities"
_AGENT_CHAT = f"{_ROOT}/agent-chat"
_AGENT_RUNS = f"{_ROOT}/agent-runs"
_IDEA_SUBMISSIONS = f"{_ROOT}/idea-submissions/mine"
_PLUGIN_CONFIG = f"{_ROOT}/plugins/me/config"
_PLUGIN_WORKFLOWS = f"{_ROOT}/plugins/me/workflows"


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
        deleted=row.get("deleted") or False,
        # Rows created before this column existed have none — fall back to the
        # built-in seed challenger, matching what actually ran for them.
        challenger_agent_key=row.get("challenger_agent_key") or CHALLENGER_AGENT_NAME,
        owner_email=row.get("owner_email"),
    )


def _json_or(value: Any, default: Any) -> Any:
    return parse_json_text(value) if value else default


def _brainstorm_session_from_row(row: dict[str, Any]) -> BrainstormSession:
    return BrainstormSession(
        id=row["id"],
        owner_sub=row["owner_sub"],
        status=row["status"],
        title=row.get("title"),
        target=row.get("target"),
        geography=row.get("geography"),
        problem=row.get("problem"),
        brief=_json_or(row.get("brief"), None),
        thread_id=row.get("thread_id"),
        turn_count=row.get("turn_count") or 0,
        chain_id=row.get("chain_id"),
        research_run_ids=_json_or(row.get("research_run_ids"), []),
        synthesis_run_id=row.get("synthesis_run_id"),
        research_findings=_json_or(row.get("research_findings"), None),
        failure_reason=row.get("failure_reason"),
        created_at=row.get("created_at"),
        deleted=row.get("deleted") or False,
        owner_email=row.get("owner_email"),
    )


def _opportunity_from_row(row: dict[str, Any]) -> BrainstormOpportunity:
    return BrainstormOpportunity(
        id=row["id"],
        owner_sub=row["owner_sub"],
        session_id=row["session_id"],
        rank=row["rank"],
        title=row["title"],
        pitch=row["pitch"],
        rationale=row.get("rationale"),
        evidence=_json_or(row.get("evidence"), None),
        model=row.get("model"),
    )


class CoreHttpGateway:
    """A :class:`~ideation.ports.CoreGateway` backed by Core's HTTP seams."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    async def create_session(
        self,
        *,
        owner_sub: str,
        seed_idea: str,
        thread_id: str,
        challenger_agent_key: str,
        owner_email: str | None = None,
    ) -> Session:
        row = await self._t.request(
            "POST",
            _SESSIONS,
            json={
                "seed_idea": seed_idea,
                "thread_id": thread_id,
                "status": GATHERING,
                "turn_count": 0,
                "challenger_agent_key": challenger_agent_key,
                # Written explicitly, not defaulted. A plugin table's columns are
                # NOT NULL with *no server default* — Core's generated migration
                # DDL does not apply declared defaults — so a column the insert
                # omits fails the whole row. Leaving this out made every
                # `POST /sessions` a 500 (#57): the Ideation Engine could not
                # start a session at all.
                "deleted": False,
                "owner_email": owner_email,
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

    async def delete_session(self, *, session_id: str) -> None:
        await self._t.request("PATCH", f"{_SESSIONS}/{session_id}", json={"deleted": True})

    async def run_chat_turn(
        self, *, thread_id: str, owner_sub: str, agent_name: str, user_text: str
    ) -> TurnResult:
        # agent_name is the registered agent key. The prompt and model come from
        # the registration in Core — with chat_agents_dynamic on, the stored
        # chat-agent row — so this method has no prompt or model parameter to
        # discard (issue #68).
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

    async def get_thread_messages(self, *, thread_id: str) -> list[dict[str, Any]]:
        resp = await self._t.request("GET", f"{_AGENT_RUNS}/threads/{thread_id}/messages")
        return list(resp.get("messages", []))

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
            "prd": parse_json_text(row.get("prd")),
            "scorecard": parse_json_text(row.get("scorecard")),
            "model": row.get("model"),
        }

    async def get_own_config(self, *, role: str) -> dict[str, Any] | None:
        """The live, admin-editable config for one of this plugin's own roles
        (e.g. "analyst"), via the SigV4-only internal read (no forwarded founder
        token needed — this data isn't founder-owned). None if never configured.
        Rows are guaranteed to exist at startup via seeding (issue #93); the
        caller (``IdeationService.finalise``) no longer falls back to a built-in
        default on ``None`` — it raises ``AgentConfigMissingError`` instead."""
        try:
            row = await self._t.request("GET", f"{_PLUGIN_CONFIG}/{role}")
        except CoreNotFoundError:
            return None
        return {"system_prompt": row["system_prompt"], "model": row["model"]}

    async def seed_own_config(self, *, config: list[dict[str, Any]]) -> list[dict[str, bool]]:
        """Seed all roles at once, insert-if-absent (issue #93). SigV4-only —
        resolved from this plugin's own service identity, so no plugin can seed
        another's config."""
        rows = await self._t.request("POST", f"{_PLUGIN_CONFIG}/seed", json=config)  # type: ignore[arg-type]
        return list(rows)

    async def seed_own_workflows(
        self, *, definitions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Declare this plugin's own workflow definitions. SigV4-only and scoped
        to this plugin's identity. An UPSERT keyed by ``definition_key`` (unlike
        the config seed), so the stored definition always matches this build."""
        rows = await self._t.request(
            "POST",
            f"{_PLUGIN_WORKFLOWS}/seed",
            json=definitions,  # type: ignore[arg-type]
        )
        return list(rows)

    async def list_active_agents(self, *, role: str) -> list[dict[str, Any]]:
        rows = await self._t.request("GET", _PLUGIN_CONFIG, params={"role": role})
        return list(rows)

    async def get_submitted_idea(self, *, owner_sub: str) -> str | None:
        try:
            row = await self._t.request("GET", _IDEA_SUBMISSIONS)
        except CoreNotFoundError:
            return None
        return row["idea"]

    # ── Brain-Storming: fan-out primitives ───────────────────────────────────

    async def request_agent_run(
        self,
        *,
        agent_name: str,
        definition: dict[str, Any],
        output_tool: dict[str, Any],
        input_payload: dict[str, Any],
        causation_id: str,
    ) -> str:
        # No thread_id: the run's whole context is input_payload. The output tool
        # rides on the definition snapshot as `output_tools` (a structured-output
        # tool, not a registry lookup). causation_id makes parallel runs a *set*:
        # without it each is its own chain root and the fan-in never sees siblings.
        snapshot = {**definition, "output_tools": [output_tool]}
        run = await self._t.request(
            "POST",
            _AGENT_RUNS,
            json={
                "agent_name": agent_name,
                "definition_snapshot": snapshot,
                "input_payload": input_payload,
                "causation_id": causation_id,
            },
        )
        return run["id"]

    async def find_chain_run(self, *, chain_id: str, agent_name: str) -> AgentRunView | None:
        # The chain listing returns summaries (no transcript), so fetch the full
        # run once one is found.
        rows = await self._t.request(
            "GET", _AGENT_RUNS, params={"causation_id": chain_id, "agent_name": agent_name}
        )
        if not rows:
            return None
        return await self.get_agent_run(run_id=rows[0]["id"])

    async def get_agent_run(self, *, run_id: str) -> AgentRunView | None:
        try:
            run = await self._t.request("GET", f"{_AGENT_RUNS}/{run_id}")
        except CoreNotFoundError:
            return None
        result = run.get("result") or {}
        model = result.get("model") or (run.get("definition_snapshot") or {}).get("model")
        return AgentRunView(
            id=run["id"],
            status=run["status"],
            messages=run.get("messages") or [],
            model=model,
            started_at=run.get("started_at"),
        )

    # ── Brain-Storming: sessions and opportunities ───────────────────────────

    async def create_brainstorm_session(
        self,
        *,
        owner_sub: str,
        target: str | None,
        geography: str | None,
        problem: str | None,
        thread_id: str,
        title: str | None = None,
        owner_email: str | None = None,
    ) -> BrainstormSession:
        # owner_sub is never sent: Core stamps it from the forwarded token. Every
        # nullable column is written explicitly — the generated DDL applies no
        # declared defaults (see create_session, #57).
        row = await self._t.request(
            "POST",
            _BS_SESSIONS,
            json={
                "title": title,
                "target": target,
                "geography": geography,
                "problem": problem,
                "thread_id": thread_id,
                "status": BS_QUALIFYING,
                "turn_count": 0,
                "deleted": False,
                "owner_email": owner_email,
            },
        )
        return _brainstorm_session_from_row(row)

    async def get_brainstorm_session(
        self, *, owner_sub: str, session_id: str
    ) -> BrainstormSession | None:
        try:
            row = await self._t.request("GET", f"{_BS_SESSIONS}/{session_id}")
        except CoreNotFoundError:
            return None
        return _brainstorm_session_from_row(row)

    async def list_brainstorm_sessions(self, *, owner_sub: str) -> list[BrainstormSession]:
        rows = await self._t.request("GET", _BS_SESSIONS)
        sessions = [_brainstorm_session_from_row(row) for row in rows]
        return [s for s in sessions if not s.deleted]

    async def update_brainstorm_session(self, *, session_id: str, **fields: Any) -> None:
        body = dict(fields)
        # Text columns holding JSON (no JSON type in Core's plugin-table map).
        for key in ("brief", "research_run_ids", "research_findings"):
            if key in body and body[key] is not None:
                body[key] = json.dumps(body[key])
        await self._t.request("PATCH", f"{_BS_SESSIONS}/{session_id}", json=body)

    async def delete_brainstorm_session(self, *, session_id: str) -> None:
        await self._t.request("PATCH", f"{_BS_SESSIONS}/{session_id}", json={"deleted": True})

    async def save_brainstorm_opportunities(
        self, *, session_id: str, opportunities: list[dict[str, Any]], model: str | None
    ) -> None:
        # One POST per row: generic CRUD has no bulk create. Sequential, so a
        # partial failure is easy to reason about.
        for rank, opp in enumerate(opportunities, start=1):
            evidence = opp.get("evidence")
            await self._t.request(
                "POST",
                _BS_OPPORTUNITIES,
                json={
                    "session_id": session_id,
                    "rank": rank,
                    "title": opp["title"],
                    "pitch": opp["pitch"],
                    "rationale": opp.get("rationale"),
                    "evidence": json.dumps(evidence) if evidence is not None else None,
                    "model": model,
                },
            )

    async def list_brainstorm_opportunities(
        self, *, owner_sub: str, session_id: str
    ) -> list[BrainstormOpportunity]:
        rows = await self._t.request("GET", _BS_OPPORTUNITIES, params={"session_id": session_id})
        opps = [_opportunity_from_row(row) for row in rows]
        return sorted(opps, key=lambda o: o.rank)
