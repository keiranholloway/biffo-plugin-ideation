"""The HTTP CoreGateway adapter: port method -> Core seam mapping.

A fake transport records every call and returns scripted responses, so these pin
the exact method/path/body the adapter sends and how it parses replies — without
any network, signing, or a live Core.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ideation.adapter import CoreHttpGateway, CoreNotFoundError
from ideation.definitions import (
    CHALLENGER_AGENT_NAME,
    analyst_definition,
    report_tool_schema,
)
from ideation.models import GATHERING
from ideation.ports import CoreGateway


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[tuple[str, str], Any] = {}

    def on(self, method: str, path: str, response: Any) -> None:
        """Script a response (a value, or an Exception to raise) for (method, path)."""
        self._responses[(method, path)] = response

    async def request(self, method, path, *, json=None, params=None):
        self.calls.append({"method": method, "path": path, "json": json, "params": params})
        response = self._responses.get((method, path), {})
        if isinstance(response, Exception):
            raise response
        return response

    def call(self, method: str, path: str) -> dict[str, Any]:
        return next(c for c in self.calls if c["method"] == method and c["path"] == path)


def _run(gw_coro):
    return asyncio.run(gw_coro)


def test_adapter_satisfies_the_core_gateway_port():
    # pyright checks the structural conformance at this annotated assignment; the
    # runtime assert just keeps the binding live.
    gateway: CoreGateway = CoreHttpGateway(FakeTransport())
    assert gateway is not None


_SESSIONS = "/api/v1/internal/owner-data/ideation_sessions"
_REPORTS = "/api/v1/internal/owner-data/ideation_reports"
_RUNS = "/api/v1/internal/agent-runs"


def _row(**over: Any) -> dict[str, Any]:
    row = {
        "id": "sess-1",
        "owner_sub": "alice",
        "seed_idea": "an idea",
        "status": GATHERING,
        "thread_id": "th-1",
        "turn_count": 0,
        "analysis_run_id": None,
        "title": None,
    }
    row.update(over)
    return row


# ── sessions (owner-data) ────────────────────────────────────────────────────────


def test_create_session_posts_without_owner_and_parses_the_row():
    t = FakeTransport()
    t.on("POST", _SESSIONS, _row())
    gw = CoreHttpGateway(t)

    session = _run(gw.create_session(owner_sub="alice", seed_idea="an idea", thread_id="th-1"))

    body = t.call("POST", _SESSIONS)["json"]
    assert body == {
        "seed_idea": "an idea",
        "thread_id": "th-1",
        "status": GATHERING,
        "turn_count": 0,
    }
    assert "owner_sub" not in body  # Core stamps the owner from the token, not the body
    assert session.id == "sess-1" and session.owner_sub == "alice"


def test_get_session_maps_404_to_none():
    t = FakeTransport()
    t.on("GET", f"{_SESSIONS}/missing", CoreNotFoundError())
    gw = CoreHttpGateway(t)
    assert _run(gw.get_session(owner_sub="alice", session_id="missing")) is None


def test_set_turn_count_and_status_patch():
    t = FakeTransport()
    gw = CoreHttpGateway(t)

    _run(gw.set_turn_count(session_id="sess-1", turn_count=3))
    assert t.call("PATCH", f"{_SESSIONS}/sess-1")["json"] == {"turn_count": 3}

    _run(gw.set_status(session_id="sess-1", status="analysing", analysis_run_id="run-9"))
    assert t.calls[-1]["json"] == {"status": "analysing", "analysis_run_id": "run-9"}


def test_set_status_omits_run_id_when_absent():
    t = FakeTransport()
    gw = CoreHttpGateway(t)
    _run(gw.set_status(session_id="sess-1", status="complete"))
    assert t.calls[-1]["json"] == {"status": "complete"}


# ── chat turn (agent-chat) ───────────────────────────────────────────────────────


def test_run_chat_turn_targets_the_agent_key_and_omits_the_prompt():
    t = FakeTransport()
    path = f"/api/v1/internal/agent-chat/{CHALLENGER_AGENT_NAME}"
    t.on("POST", path, {"reply": "Why now?", "model": "m", "output_tokens": 3})
    gw = CoreHttpGateway(t)

    result = _run(
        gw.run_chat_turn(
            thread_id="th-1",
            owner_sub="alice",
            agent_name=CHALLENGER_AGENT_NAME,
            system_prompt="SECRET PROMPT",
            user_text="my answer",
            model="chat/m",
        )
    )

    body = t.call("POST", path)["json"]
    assert body == {"message": "my answer", "thread_id": "th-1"}
    assert "SECRET PROMPT" not in str(body)  # the prompt is Core's, resolved by key
    assert result.reply == "Why now?" and result.model == "m"


# ── analysis (thread read + agent-run create) ────────────────────────────────────


def test_request_analysis_reads_the_thread_then_creates_the_run():
    t = FakeTransport()
    t.on(
        "GET",
        f"{_RUNS}/threads/th-1/messages",
        {"messages": [{"role": "user", "content": "hi"}]},
    )
    t.on("POST", _RUNS, {"id": "run-9"})
    gw = CoreHttpGateway(t)

    run_id = _run(
        gw.request_analysis(
            thread_id="th-1",
            owner_sub="alice",
            agent_name="ideation-analyst",
            definition=analyst_definition(model="a/m"),
            output_tool=report_tool_schema(),
        )
    )

    assert run_id == "run-9"
    body = t.call("POST", _RUNS)["json"]
    # the analyst def carries only registry tools; the report is an OUTPUT tool
    assert body["definition_snapshot"]["tools"] == ["web_search"]
    assert (
        body["definition_snapshot"]["output_tools"][0]["function"]["name"]
        == "submit_ideation_report"
    )
    # the run is handed the thread conversation to reason over
    assert body["input_payload"]["conversation"] == [{"role": "user", "content": "hi"}]
    assert body["thread_id"] == "th-1"


def test_get_run_parses_status_messages_and_model():
    t = FakeTransport()
    t.on(
        "GET",
        f"{_RUNS}/run-9",
        {
            "id": "run-9",
            "status": "completed",
            "messages": [{"role": "assistant", "tool_calls": []}],
            "result": {"model": "a/m"},
        },
    )
    gw = CoreHttpGateway(t)

    run = _run(gw.get_run(run_id="run-9"))
    assert run is not None
    assert run.status == "completed" and run.model == "a/m"
    assert run.messages == [{"role": "assistant", "tool_calls": []}]


def test_get_run_maps_404_to_none():
    t = FakeTransport()
    t.on("GET", f"{_RUNS}/gone", CoreNotFoundError())
    gw = CoreHttpGateway(t)
    assert _run(gw.get_run(run_id="gone")) is None


# ── reports (owner-data) ─────────────────────────────────────────────────────────


def test_save_report_posts_without_owner():
    t = FakeTransport()
    gw = CoreHttpGateway(t)
    _run(gw.save_report(session_id="sess-1", prd={"p": 1}, scorecard={"s": 2}, model="m"))
    body = t.call("POST", _REPORTS)["json"]
    # prd/scorecard are JSON-serialised for the Text columns (Core has no JSON type)
    assert body == {
        "session_id": "sess-1",
        "prd": '{"p": 1}',
        "scorecard": '{"s": 2}',
        "model": "m",
    }
    assert "owner_sub" not in body


def test_get_report_parses_the_json_text_columns():
    t = FakeTransport()
    # Core returns the Text columns verbatim — JSON strings, as they were stored.
    t.on(
        "GET",
        _REPORTS,
        [
            {
                "prd": '{"p": 1}',
                "scorecard": '{"s": 2}',
                "model": "m",
                "owner_sub": "alice",
            }
        ],
    )
    gw = CoreHttpGateway(t)

    report = _run(gw.get_report(session_id="sess-1"))
    assert t.call("GET", _REPORTS)["params"] == {"session_id": "sess-1"}
    assert report == {"prd": {"p": 1}, "scorecard": {"s": 2}, "model": "m"}


def test_get_report_none_when_empty():
    t = FakeTransport()
    t.on("GET", _REPORTS, [])
    gw = CoreHttpGateway(t)
    assert _run(gw.get_report(session_id="sess-1")) is None
