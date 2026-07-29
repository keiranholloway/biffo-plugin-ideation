"""The HTTP CoreGateway adapter: port method -> Core seam mapping.

A fake transport records every call and returns scripted responses, so these pin
the exact method/path/body the adapter sends and how it parses replies — without
any network, signing, or a live Core.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
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

    session = _run(
        gw.create_session(
            owner_sub="alice",
            seed_idea="an idea",
            thread_id="th-1",
            challenger_agent_key=CHALLENGER_AGENT_NAME,
        )
    )

    body = t.call("POST", _SESSIONS)["json"]
    assert body == {
        "seed_idea": "an idea",
        "thread_id": "th-1",
        "status": GATHERING,
        "turn_count": 0,
        "challenger_agent_key": CHALLENGER_AGENT_NAME,
        "deleted": False,
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


def test_delete_session_patches_with_deleted_true():
    t = FakeTransport()
    gw = CoreHttpGateway(t)
    _run(gw.delete_session(session_id="sess-1"))
    assert t.call("PATCH", f"{_SESSIONS}/sess-1")["json"] == {"deleted": True}


def test_session_from_row_maps_deleted_field():
    from ideation.adapter import _session_from_row

    row = _row(deleted=True)
    session = _session_from_row(row)
    assert session.deleted is True

    row_no_deleted = _row()
    # deleted key was not in original _row, so it won't be there
    if "deleted" in row_no_deleted:
        del row_no_deleted["deleted"]
    session_no_deleted = _session_from_row(row_no_deleted)
    assert session_no_deleted.deleted is False


def test_list_sessions_maps_rows_including_created_at():
    t = FakeTransport()
    t.on(
        "GET",
        _SESSIONS,
        [
            _row(id="s1", created_at="2026-07-25T10:00:00Z"),
            _row(id="s2", created_at="2026-07-24T15:30:00Z"),
        ],
    )
    gw = CoreHttpGateway(t)

    sessions = _run(gw.list_sessions(owner_sub="alice"))

    assert t.call("GET", _SESSIONS)["params"] is None
    assert len(sessions) == 2
    assert sessions[0].id == "s1"
    assert sessions[0].created_at == "2026-07-25T10:00:00Z"
    assert sessions[1].id == "s2"
    assert sessions[1].created_at == "2026-07-24T15:30:00Z"


# ── chat turn (agent-chat) ───────────────────────────────────────────────────────


def test_run_chat_turn_targets_the_agent_key_and_sends_only_the_message():
    t = FakeTransport()
    path = f"/api/v1/internal/agent-chat/{CHALLENGER_AGENT_NAME}"
    t.on("POST", path, {"reply": "Why now?", "model": "m", "output_tokens": 3})
    gw = CoreHttpGateway(t)

    result = _run(
        gw.run_chat_turn(
            thread_id="th-1",
            owner_sub="alice",
            agent_name=CHALLENGER_AGENT_NAME,
            user_text="my answer",
        )
    )

    body = t.call("POST", path)["json"]
    assert body == {"message": "my answer", "thread_id": "th-1"}
    # The model on the result is the one Core resolved from the registration
    # and reported back — this side never asked for one.
    assert result.reply == "Why now?" and result.model == "m"


def test_run_chat_turn_has_no_prompt_or_model_parameter_to_discard():
    """Issue #68: it used to require both keyword args and send neither.

    The behaviour was right — Core resolves the prompt and model from the
    agent's registration, which with ``chat_agents_dynamic: true`` is the
    stored chat-agent row, so the plugin must not override them. The defect was
    a signature promising control it does not have: read alongside service.py
    it said the challenger ran on a plugin-side constant and its stored row was
    inert, which is the opposite of the truth. Deleting them is the fix;
    wiring them through would have created the bug the signature implied.
    """
    import inspect

    params = inspect.signature(CoreHttpGateway.run_chat_turn).parameters

    assert set(params) == {"self", "thread_id", "owner_sub", "agent_name", "user_text"}


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
    # No registry tools: web_search is dropped on any deployment without a Brave
    # credential, so research rides on the model slug's :online suffix instead.
    # The report is an OUTPUT tool and was never in here.
    assert "tools" not in body["definition_snapshot"]
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


# ── submitted idea ──────────────────────────────────────────────────────────


def test_get_submitted_idea_returns_the_idea():
    t = FakeTransport()
    t.on("GET", "/api/v1/internal/idea-submissions/mine", {"idea": "build a coaching app"})
    gw = CoreHttpGateway(t)

    idea = _run(gw.get_submitted_idea(owner_sub="alice"))

    assert idea == "build a coaching app"


def test_get_submitted_idea_maps_404_to_none():
    t = FakeTransport()
    t.on("GET", "/api/v1/internal/idea-submissions/mine", CoreNotFoundError())
    gw = CoreHttpGateway(t)

    idea = _run(gw.get_submitted_idea(owner_sub="alice"))

    assert idea is None


# ── own config (live, admin-editable role config) ────────────────────────────


def test_get_own_config_returns_the_row():
    t = FakeTransport()
    t.on(
        "GET",
        "/api/v1/internal/plugins/me/config/analyst",
        {"system_prompt": "Analyze rigorously.", "model": "some/model"},
    )
    gw = CoreHttpGateway(t)

    config = _run(gw.get_own_config(role="analyst"))

    assert config == {"system_prompt": "Analyze rigorously.", "model": "some/model"}


def test_get_own_config_maps_404_to_none():
    t = FakeTransport()
    t.on("GET", "/api/v1/internal/plugins/me/config/analyst", CoreNotFoundError())
    gw = CoreHttpGateway(t)

    config = _run(gw.get_own_config(role="analyst"))

    assert config is None


def test_list_active_agents_passes_the_role_filter_and_returns_rows():
    t = FakeTransport()
    rows = [{"agent_key": "k1", "agent_name": "Skeptic"}, {"agent_key": "k2", "agent_name": "Ally"}]
    t.on("GET", "/api/v1/internal/plugins/me/config", rows)
    gw = CoreHttpGateway(t)

    result = _run(gw.list_active_agents(role="challenger"))

    assert result == rows
    assert t.call("GET", "/api/v1/internal/plugins/me/config")["params"] == {"role": "challenger"}


# ── session row mapping ──────────────────────────────────────────────────────


def test_session_from_row_maps_challenger_agent_key():
    t = FakeTransport()
    t.on("POST", _SESSIONS, _row(challenger_agent_key="custom-agent"))
    gw = CoreHttpGateway(t)

    session = _run(
        gw.create_session(
            owner_sub="alice",
            seed_idea="an idea",
            thread_id="th-1",
            challenger_agent_key="custom-agent",
        )
    )

    assert session.challenger_agent_key == "custom-agent"


def test_session_from_row_falls_back_to_the_built_in_challenger_when_missing():
    t = FakeTransport()
    t.on("POST", _SESSIONS, _row())  # no challenger_agent_key in the row (pre-existing session)
    gw = CoreHttpGateway(t)

    session = _run(
        gw.create_session(
            owner_sub="alice",
            seed_idea="an idea",
            thread_id="th-1",
            challenger_agent_key=CHALLENGER_AGENT_NAME,
        )
    )

    assert session.challenger_agent_key == CHALLENGER_AGENT_NAME


def test_insert_writes_every_column_the_manifest_requires():
    """A NOT NULL plugin column the insert omits fails the whole row.

    This is the defect in #57, and it took the Ideation Engine down completely:
    `deleted` was declared `nullable: false`, `create_session` never sent it, and
    every `POST /sessions` came back 500 from a NotNullViolationError.

    Two things made it survive a green suite. Plugin tables are NOT NULL with
    **no server default** — Core's generated migration DDL does not apply declared
    defaults — so the database is the only place the omission shows. And the
    payload assertion above pinned the body *exactly*, which locked the broken
    shape in rather than catching it.

    So this derives the expectation from `biffo.plugin.json` instead: every
    required column must appear in the insert. A column added to the manifest
    without being written now fails here, at the point it is added.
    """
    manifest = json.loads((Path(__file__).resolve().parents[1] / "biffo.plugin.json").read_text())
    table = next(t for t in manifest["tables"] if t["name"] == "ideation_sessions")
    required = {c["name"] for c in table["columns"] if c.get("nullable") is False}

    # Core stamps the owner from the forwarded token and rejects a body that
    # sends one — asking for another founder's row is exactly what that prevents
    # (ADR-0017 §5), so it is required in the table and must not be in the body.
    core_owned = {"owner_sub"}

    t = FakeTransport()
    t.on("POST", _SESSIONS, _row())
    _run(
        CoreHttpGateway(t).create_session(
            owner_sub="alice",
            seed_idea="an idea",
            thread_id="th-1",
            challenger_agent_key=CHALLENGER_AGENT_NAME,
        )
    )
    body = t.call("POST", _SESSIONS)["json"]

    assert sorted(required - core_owned - set(body)) == []
    # Guards the guard: an empty `required` would make the line above vacuous.
    assert len(required - core_owned) >= 2
