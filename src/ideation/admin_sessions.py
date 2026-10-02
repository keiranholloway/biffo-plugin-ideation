"""Admin read-model over every user's Brain-Storm sessions.

Pure with respect to I/O: it takes the same ``Transport`` the adapter uses (a
SigV4-signed call carrying the *admin's* token) and reads three Core seams:

- ``/internal/owner-data-admin/<table>`` — Core's read-only, admin-gated,
  tenant-scoped cross-owner read of this plugin's owner-scoped tables
  (biffo-template#2224). Core, not this module, enforces that the forwarded
  user is an admin.
- ``/internal/agent-runs/threads/{id}/usage`` and ``POST /internal/agent-runs/usage``
  — per-run model, tokens and ``cost_usd`` (biffo-template#2225).
- ``/internal/agent-runs/threads/{id}/messages`` — the qualifying transcript.

Unpriced runs (``cost_usd`` null) are counted and flagged; they are never summed
as zero, and a session with no priced run has a ``null`` total, not ``0``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .adapter import (
    CoreNotFoundError,
    Transport,
    _brainstorm_session_from_row,
    _opportunity_from_row,
    _session_from_row,
)
from .json_text import parse_json_text
from .models import BrainstormSession, Session
from .service import visible_turns

_ROOT = "/api/v1/internal"
_ADMIN_SESSIONS = f"{_ROOT}/owner-data-admin/brainstorm_sessions"
_ADMIN_OPPORTUNITIES = f"{_ROOT}/owner-data-admin/brainstorm_opportunities"
_ADMIN_PT_SESSIONS = f"{_ROOT}/owner-data-admin/ideation_sessions"
_ADMIN_PT_REPORTS = f"{_ROOT}/owner-data-admin/ideation_reports"
_AGENT_RUNS = f"{_ROOT}/agent-runs"

_PAGE = 100
_MAX_PAGES = 100  # 10k sessions: a hard stop, not an expected size
_USAGE_BATCH = 200  # Core caps a usage batch at 200 ids
_USAGE_CONCURRENCY = 8

SORT_KEYS = ("date", "cost")


async def _list_all(transport: Transport, path: str, **params: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(_MAX_PAGES):
        batch = await transport.request(
            "GET", path, params={**params, "limit": _PAGE, "offset": page * _PAGE}
        )
        batch = list(batch or [])
        rows.extend(batch)
        if len(batch) < _PAGE:
            break
    return rows


def _run_rows(usage: Any) -> list[dict[str, Any]]:
    runs = (usage or {}).get("runs") if isinstance(usage, dict) else None
    return [r for r in runs or [] if isinstance(r, dict)]


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over per-run rows: priced cost summed, unpriced runs counted."""
    priced = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    return {
        "runs": len(rows),
        "total_cost_usd": round(sum(priced), 6) if priced else None,
        "priced_runs": len(priced),
        "unpriced_runs": len(rows) - len(priced),
        "input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
        "output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
    }


async def _runs_by_id(transport: Transport, run_ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(run_ids), _USAGE_BATCH):
        usage = await transport.request(
            "POST",
            f"{_AGENT_RUNS}/usage",
            json={"run_ids": run_ids[i : i + _USAGE_BATCH]},
        )
        out.extend(_run_rows(usage))
    return out


async def session_usage_rows(transport: Transport, s: BrainstormSession) -> list[dict[str, Any]]:
    """Every run of a session, labelled by stage, de-duplicated by run id."""
    chat = _run_rows(
        await transport.request("GET", f"{_AGENT_RUNS}/threads/{s.thread_id}/usage")
        if s.thread_id
        else None
    )
    research_ids = [i for i in s.research_run_ids if i]
    pipeline_ids = list(research_ids)
    if s.synthesis_run_id:
        pipeline_ids.append(s.synthesis_run_id)
    pipeline = await _runs_by_id(transport, pipeline_ids) if pipeline_ids else []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(stage: str, run: dict[str, Any], label: str) -> None:
        run_id = str(run.get("id"))
        if run_id in seen:
            return
        seen.add(run_id)
        rows.append(
            {
                "stage": stage,
                "label": label,
                "run_id": run_id,
                "agent_name": run.get("agent_name"),
                "model": run.get("model"),
                "status": run.get("status"),
                "input_tokens": run.get("input_tokens"),
                "output_tokens": run.get("output_tokens"),
                "cost_usd": run.get("cost_usd"),
                "priced": run.get("cost_usd") is not None,
            }
        )

    for run in pipeline:
        if run.get("id") == s.synthesis_run_id:
            add("synthesis", run, "Synthesis")
        else:
            add("research", run, run.get("agent_name") or "Research agent")
    # Pipeline stages first claim their runs, so a run that is on both the
    # thread and the pipeline lists is never counted twice.
    chat_rows: list[dict[str, Any]] = []
    for run in chat:
        if run.get("id") not in seen:
            chat_rows.append(run)
    for turn, run in enumerate(chat_rows, start=1):
        add("qualifying", run, f"Qualifying turn {turn}")
    order = {"qualifying": 0, "research": 1, "synthesis": 2}
    rows.sort(key=lambda r: order[r["stage"]])
    return rows


def _owner_label(s: BrainstormSession) -> dict[str, Any]:
    return {
        "owner_sub": s.owner_sub,
        "owner_email": s.owner_email,
        # Sessions created before the email was recorded have only the sub.
        "owner_email_known": bool(s.owner_email),
        "owner_display": s.owner_email or s.owner_sub,
    }


def _summary(s: BrainstormSession) -> dict[str, Any]:
    return {
        "session_id": s.id,
        **_owner_label(s),
        "title": s.title,
        "target": s.target,
        "status": s.status,
        "created_at": s.created_at,
        "turn_count": s.turn_count,
        "deleted": s.deleted,
    }


async def list_sessions(
    transport: Transport,
    *,
    user: str | None = None,
    status: str | None = None,
    sort: str = "date",
    order: str = "desc",
) -> list[dict[str, Any]]:
    """Every user's sessions (soft-deleted included, marked ``deleted``)."""
    rows = await _list_all(transport, _ADMIN_SESSIONS)
    sessions = [_brainstorm_session_from_row(r) for r in rows]
    if user:
        needle = user.strip().lower()
        sessions = [
            s
            for s in sessions
            if s.owner_sub.lower() == needle or needle in (s.owner_email or "").lower()
        ]
    if status:
        sessions = [s for s in sessions if s.status == status]

    gate = asyncio.Semaphore(_USAGE_CONCURRENCY)

    async def with_cost(s: BrainstormSession) -> dict[str, Any]:
        item = _summary(s)
        async with gate:
            try:
                item["cost"] = summarise(await session_usage_rows(transport, s))
                item["cost_error"] = False
            except Exception:  # noqa: BLE001 - one session's usage must not sink the list
                item["cost"] = None
                item["cost_error"] = True
        return item

    items = list(await asyncio.gather(*(with_cost(s) for s in sessions)))

    reverse = order != "asc"
    if sort == "cost":
        # Sessions with no priced cost sort last whichever the direction.
        known = [i for i in items if i["cost"] and i["cost"]["total_cost_usd"] is not None]
        unknown = [i for i in items if i not in known]
        known.sort(key=lambda i: i["cost"]["total_cost_usd"], reverse=reverse)
        return known + unknown
    items.sort(key=lambda i: i["created_at"] or "", reverse=reverse)
    return items


async def get_session_detail(transport: Transport, session_id: str) -> dict[str, Any] | None:
    """One session read-only: brief, transcript, opportunities, cost breakdown."""
    try:
        row = await transport.request("GET", f"{_ADMIN_SESSIONS}/{session_id}")
    except CoreNotFoundError:
        return None
    s = _brainstorm_session_from_row(row)

    transcript: list[dict[str, str]] = []
    if s.thread_id:
        raw = await transport.request("GET", f"{_AGENT_RUNS}/threads/{s.thread_id}/messages")
        transcript = visible_turns(list((raw or {}).get("messages", [])), strip_brief_state=True)

    opp_rows = await _list_all(transport, _ADMIN_OPPORTUNITIES, session_id=session_id)
    opportunities = sorted((_opportunity_from_row(r) for r in opp_rows), key=lambda o: o.rank)

    usage = await session_usage_rows(transport, s)
    return {
        **_summary(s),
        "geography": s.geography,
        "problem": s.problem,
        "brief": s.brief,
        "failure_reason": s.failure_reason,
        "transcript": transcript,
        "opportunities": [
            {
                "rank": o.rank,
                "title": o.title,
                "pitch": o.pitch,
                "rationale": o.rationale,
                "evidence": o.evidence,
                "model": o.model,
            }
            for o in opportunities
        ],
        "cost": {"rows": usage, **summarise(usage)},
    }


# ── Pressure Test sessions ───────────────────────────────────────────────────
#
# Same shape as the Brain-Storm read-model above (and the same ``summarise``,
# paging and cost semantics); only the tables and the run stages differ: the
# challenger chat is one run per turn on ``thread_id``, and the analyst run is
# ``analysis_run_id``.


def _run_row(stage: str, label: str, run: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": stage,
        "label": label,
        "run_id": str(run.get("id")),
        "agent_name": run.get("agent_name"),
        "model": run.get("model"),
        "status": run.get("status"),
        "input_tokens": run.get("input_tokens"),
        "output_tokens": run.get("output_tokens"),
        "cost_usd": run.get("cost_usd"),
        "priced": run.get("cost_usd") is not None,
    }


async def pressure_test_usage_rows(transport: Transport, s: Session) -> list[dict[str, Any]]:
    """The challenger chat runs plus the analyst run, de-duplicated by run id."""
    chat = _run_rows(
        await transport.request("GET", f"{_AGENT_RUNS}/threads/{s.thread_id}/usage")
        if s.thread_id
        else None
    )
    analysis = await _runs_by_id(transport, [s.analysis_run_id]) if s.analysis_run_id else []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    # The analyst run claims its id first so it is never also counted as a turn.
    for run in analysis:
        seen.add(str(run.get("id")))
        rows.append(_run_row("analysis", "Analyst run", run))
    turn = 0
    chat_rows: list[dict[str, Any]] = []
    for run in chat:
        if str(run.get("id")) in seen:
            continue
        seen.add(str(run.get("id")))
        turn += 1
        chat_rows.append(_run_row("chat", f"Challenger turn {turn}", run))
    return chat_rows + rows


def _pt_summary(s: Session) -> dict[str, Any]:
    return {
        "session_id": s.id,
        "owner_sub": s.owner_sub,
        "owner_email": s.owner_email,
        "owner_email_known": bool(s.owner_email),
        "owner_display": s.owner_email or s.owner_sub,
        "title": s.title,
        "target": None,
        "seed_idea": s.seed_idea,
        "status": s.status,
        "created_at": s.created_at,
        "turn_count": s.turn_count,
        "deleted": s.deleted,
    }


async def list_pressure_test_sessions(
    transport: Transport,
    *,
    user: str | None = None,
    status: str | None = None,
    sort: str = "date",
    order: str = "desc",
) -> list[dict[str, Any]]:
    """Every user's Pressure Test sessions (soft-deleted included, marked)."""
    rows = await _list_all(transport, _ADMIN_PT_SESSIONS)
    sessions = [_session_from_row(r) for r in rows]
    if user:
        needle = user.strip().lower()
        sessions = [
            s
            for s in sessions
            if s.owner_sub.lower() == needle or needle in (s.owner_email or "").lower()
        ]
    if status:
        sessions = [s for s in sessions if s.status == status]

    gate = asyncio.Semaphore(_USAGE_CONCURRENCY)

    async def with_cost(s: Session) -> dict[str, Any]:
        item = _pt_summary(s)
        async with gate:
            try:
                item["cost"] = summarise(await pressure_test_usage_rows(transport, s))
                item["cost_error"] = False
            except Exception:  # noqa: BLE001 - one session's usage must not sink the list
                item["cost"] = None
                item["cost_error"] = True
        return item

    items = list(await asyncio.gather(*(with_cost(s) for s in sessions)))
    reverse = order != "asc"
    if sort == "cost":
        known = [i for i in items if i["cost"] and i["cost"]["total_cost_usd"] is not None]
        unknown = [i for i in items if i not in known]
        known.sort(key=lambda i: i["cost"]["total_cost_usd"], reverse=reverse)
        return known + unknown
    items.sort(key=lambda i: i["created_at"] or "", reverse=reverse)
    return items


async def get_pressure_test_detail(transport: Transport, session_id: str) -> dict[str, Any] | None:
    """One Pressure Test session read-only: seed idea, transcript, report, cost."""
    try:
        row = await transport.request("GET", f"{_ADMIN_PT_SESSIONS}/{session_id}")
    except CoreNotFoundError:
        return None
    s = _session_from_row(row)

    transcript: list[dict[str, str]] = []
    if s.thread_id:
        raw = await transport.request("GET", f"{_AGENT_RUNS}/threads/{s.thread_id}/messages")
        transcript = visible_turns(list((raw or {}).get("messages", [])))

    report_rows = await _list_all(transport, _ADMIN_PT_REPORTS, session_id=session_id)
    report = None
    if report_rows:
        r = report_rows[0]
        report = {
            "prd": parse_json_text(r.get("prd")),
            "scorecard": parse_json_text(r.get("scorecard")),
            "model": r.get("model"),
        }

    usage = await pressure_test_usage_rows(transport, s)
    return {
        **_pt_summary(s),
        "challenger_agent_key": s.challenger_agent_key,
        "transcript": transcript,
        "report": report,
        "cost": {"rows": usage, **summarise(usage)},
    }
