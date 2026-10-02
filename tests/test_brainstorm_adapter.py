"""Brain-Storming gateway plumbing: fan-out primitives + session/opportunity CRUD.

A fake transport records every call, pinning the exact method/path/body the
adapter sends and how it parses replies. Also checks the fake gateway used by
service tests cannot drift from the port.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from ideation.adapter import CoreHttpGateway, CoreNotFoundError
from ideation.models import AgentRunView, BrainstormOpportunity, BrainstormSession
from ideation.ports import CoreGateway

_BS = "/api/v1/internal/owner-data/brainstorm_sessions"
_OPPS = "/api/v1/internal/owner-data/brainstorm_opportunities"
_RUNS = "/api/v1/internal/agent-runs"


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[tuple[str, str], Any] = {}

    def on(self, method: str, path: str, response: Any) -> None:
        self._responses[(method, path)] = response

    async def request(self, method, path, *, json=None, params=None):
        self.calls.append({"method": method, "path": path, "json": json, "params": params})
        response = self._responses.get((method, path), {})
        if isinstance(response, Exception):
            raise response
        return response

    def call(self, method: str, path: str) -> dict[str, Any]:
        return next(c for c in self.calls if c["method"] == method and c["path"] == path)

    def calls_to(self, method: str, path: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]


def _run(coro):
    return asyncio.run(coro)


def _row(**over: Any) -> dict[str, Any]:
    row = {
        "id": "bs-1",
        "owner_sub": "alice",
        "status": "qualifying",
        "title": None,
        "target": "logistics",
        "geography": "UK",
        "problem": "late deliveries",
        "brief": None,
        "thread_id": "th-1",
        "turn_count": 0,
        "chain_id": None,
        "research_run_ids": None,
        "synthesis_run_id": None,
        "failure_reason": None,
        "deleted": False,
    }
    row.update(over)
    return row


def test_adapter_satisfies_the_port():
    gateway: CoreGateway = CoreHttpGateway(FakeTransport())
    assert gateway is not None


def test_port_methods_are_all_implemented_with_matching_signatures():
    for name, value in vars(CoreGateway).items():
        if name.startswith("_") or not callable(value):
            continue
        adapter_sig = inspect.signature(getattr(CoreHttpGateway, name))
        port_sig = inspect.signature(value)
        assert adapter_sig.parameters.keys() == port_sig.parameters.keys(), name


# ── fan-out primitives ───────────────────────────────────────────────────────


def test_request_agent_run_sends_causation_id_and_no_thread():
    t = FakeTransport()
    t.on("POST", _RUNS, {"id": "run-9"})
    tool = {"name": "submit", "input_schema": {}}
    run_id = _run(
        CoreHttpGateway(t).request_agent_run(
            agent_name="research-a",
            definition={"model": "m", "system_prompt": "p"},
            output_tool=tool,
            input_payload={"brief": "b"},
            causation_id="chain-1",
        )
    )
    assert run_id == "run-9"
    body = t.call("POST", _RUNS)["json"]
    assert body["causation_id"] == "chain-1"
    assert body["agent_name"] == "research-a"
    assert body["input_payload"] == {"brief": "b"}
    assert body["definition_snapshot"]["output_tools"] == [tool]
    assert body["definition_snapshot"]["model"] == "m"
    assert "thread_id" not in body


def test_find_chain_run_returns_none_until_the_engine_fires_it():
    t = FakeTransport()
    t.on("GET", _RUNS, [])
    assert _run(CoreHttpGateway(t).find_chain_run(chain_id="c", agent_name="syn")) is None
    assert t.call("GET", _RUNS)["params"] == {"causation_id": "c", "agent_name": "syn"}


def test_find_chain_run_fetches_the_full_run():
    t = FakeTransport()
    t.on("GET", _RUNS, [{"id": "run-2"}])
    t.on(
        "GET",
        f"{_RUNS}/run-2",
        {"id": "run-2", "status": "completed", "messages": [{"role": "assistant"}]},
    )
    view = _run(CoreHttpGateway(t).find_chain_run(chain_id="c", agent_name="syn"))
    assert view is not None and view.id == "run-2"
    assert view.messages == [{"role": "assistant"}]


def test_get_agent_run_maps_404_to_none():
    t = FakeTransport()
    t.on("GET", f"{_RUNS}/gone", CoreNotFoundError("404"))
    assert _run(CoreHttpGateway(t).get_agent_run(run_id="gone")) is None


def test_get_agent_run_parses_model_and_started_at():
    t = FakeTransport()
    t.on(
        "GET",
        f"{_RUNS}/r",
        {
            "id": "r",
            "status": "running",
            "definition_snapshot": {"model": "snap"},
            "started_at": "2026-01-01T00:00:00Z",
        },
    )
    view = _run(CoreHttpGateway(t).get_agent_run(run_id="r"))
    assert view is not None
    assert view == AgentRunView(
        id="r", status="running", messages=[], model="snap", started_at="2026-01-01T00:00:00Z"
    )
    assert not view.is_terminal


def test_result_model_wins_over_snapshot_model():
    t = FakeTransport()
    t.on(
        "GET",
        f"{_RUNS}/r",
        {
            "id": "r",
            "status": "completed",
            "result": {"model": "real"},
            "definition_snapshot": {"model": "snap"},
        },
    )
    view = _run(CoreHttpGateway(t).get_agent_run(run_id="r"))
    assert view is not None
    assert view.model == "real"


def test_agent_run_view_state_properties():
    assert AgentRunView(id="a", status="completed").succeeded
    assert AgentRunView(id="a", status="completed").is_terminal
    failed_unclaimed = AgentRunView(id="a", status="failed")
    assert failed_unclaimed.is_terminal and not failed_unclaimed.succeeded
    assert failed_unclaimed.never_started
    assert not AgentRunView(id="a", status="failed", started_at="t").never_started
    assert not AgentRunView(id="a", status="completed").never_started
    assert not AgentRunView(id="a", status="pending").never_started


# ── sessions ─────────────────────────────────────────────────────────────────


def test_create_brainstorm_session_posts_without_owner_and_writes_defaults():
    t = FakeTransport()
    t.on("POST", _BS, _row())
    s = _run(
        CoreHttpGateway(t).create_brainstorm_session(
            owner_sub="alice",
            target="logistics",
            geography="UK",
            problem="late deliveries",
            thread_id="th-1",
        )
    )
    body = t.call("POST", _BS)["json"]
    assert "owner_sub" not in body
    assert body["status"] == "qualifying"
    assert body["turn_count"] == 0
    assert body["deleted"] is False
    assert body["thread_id"] == "th-1"
    assert isinstance(s, BrainstormSession)
    assert s.id == "bs-1" and s.target == "logistics"


def test_get_brainstorm_session_maps_404_to_none():
    t = FakeTransport()
    t.on("GET", f"{_BS}/x", CoreNotFoundError("404"))
    assert _run(CoreHttpGateway(t).get_brainstorm_session(owner_sub="a", session_id="x")) is None


def test_session_row_parses_json_text_columns():
    t = FakeTransport()
    t.on(
        "GET",
        f"{_BS}/bs-1",
        _row(
            brief=json.dumps({"target": "logistics"}),
            research_run_ids=json.dumps(["a", "b"]),
            chain_id="chain-1",
            deleted=None,
            turn_count=None,
        ),
    )
    s = _run(CoreHttpGateway(t).get_brainstorm_session(owner_sub="alice", session_id="bs-1"))
    assert s is not None
    assert s.brief == {"target": "logistics"}
    assert s.research_run_ids == ["a", "b"]
    assert s.chain_id == "chain-1"
    assert s.deleted is False
    assert s.turn_count == 0


def test_list_brainstorm_sessions_hides_deleted_and_sends_no_params():
    t = FakeTransport()
    t.on("GET", _BS, [_row(id="a"), _row(id="b", deleted=True)])
    sessions = _run(CoreHttpGateway(t).list_brainstorm_sessions(owner_sub="alice"))
    assert [s.id for s in sessions] == ["a"]
    assert t.call("GET", _BS)["params"] is None


def test_update_brainstorm_session_patches_and_serialises_json_fields():
    t = FakeTransport()
    _run(
        CoreHttpGateway(t).update_brainstorm_session(
            session_id="bs-1",
            status="researching",
            chain_id="c",
            research_run_ids=["r1", "r2"],
            brief={"k": "v"},
        )
    )
    body = t.call("PATCH", f"{_BS}/bs-1")["json"]
    assert body["status"] == "researching"
    assert body["chain_id"] == "c"
    assert json.loads(body["research_run_ids"]) == ["r1", "r2"]
    assert json.loads(body["brief"]) == {"k": "v"}


def test_update_brainstorm_session_sends_only_given_fields():
    t = FakeTransport()
    _run(CoreHttpGateway(t).update_brainstorm_session(session_id="bs-1", status="failed"))
    assert t.call("PATCH", f"{_BS}/bs-1")["json"] == {"status": "failed"}


def test_delete_brainstorm_session_is_a_soft_delete():
    t = FakeTransport()
    _run(CoreHttpGateway(t).delete_brainstorm_session(session_id="bs-1"))
    assert t.call("PATCH", f"{_BS}/bs-1")["json"] == {"deleted": True}
    assert not [c for c in t.calls if c["method"] == "DELETE"]


# ── opportunities ────────────────────────────────────────────────────────────


def test_save_opportunities_posts_one_ranked_row_each_without_owner():
    t = FakeTransport()
    _run(
        CoreHttpGateway(t).save_brainstorm_opportunities(
            session_id="bs-1",
            opportunities=[
                {"title": "A", "pitch": "pa", "rationale": "ra", "evidence": ["e1"]},
                {"title": "B", "pitch": "pb"},
            ],
            model="m",
        )
    )
    posts = t.calls_to("POST", _OPPS)
    assert [p["json"]["rank"] for p in posts] == [1, 2]
    assert all("owner_sub" not in p["json"] for p in posts)
    assert posts[0]["json"]["session_id"] == "bs-1"
    assert posts[0]["json"]["model"] == "m"
    assert json.loads(posts[0]["json"]["evidence"]) == ["e1"]
    assert posts[1]["json"]["evidence"] is None
    assert posts[1]["json"]["rationale"] is None


def test_list_opportunities_filters_by_session_and_sorts_by_rank():
    t = FakeTransport()
    base = {"owner_sub": "alice", "session_id": "bs-1", "pitch": "p"}
    t.on(
        "GET",
        _OPPS,
        [
            {**base, "id": "o2", "rank": 2, "title": "B", "evidence": None},
            {**base, "id": "o1", "rank": 1, "title": "A", "evidence": json.dumps(["x"])},
        ],
    )
    opps = _run(
        CoreHttpGateway(t).list_brainstorm_opportunities(owner_sub="alice", session_id="bs-1")
    )
    assert t.call("GET", _OPPS)["params"] == {"session_id": "bs-1"}
    assert [o.id for o in opps] == ["o1", "o2"]
    assert isinstance(opps[0], BrainstormOpportunity)
    assert opps[0].evidence == ["x"]
    assert opps[1].evidence is None


def test_chat_turn_brief_round_trips_through_adapter():
    from ideation.brainstorm_definitions import BriefState
    from ideation.models import TurnResult
    from ideation.service import BrainstormService

    t = FakeTransport()
    t.on("GET", f"{_BS}/bs-1", _row(id="bs-1", status="qualifying", thread_id="th", turn_count=0))

    state = {"ready": True, "summary": "SMEs in the UK losing cash to late invoices"}

    class Core(CoreHttpGateway):
        async def run_chat_turn(self, **kw):
            return TurnResult(reply=f"Got it.\n<brief_state>{json.dumps(state)}</brief_state>")

    svc = BrainstormService(Core(t))
    _run(svc.chat_turn(owner_sub="alice", session_id="bs-1", user_message="x"))
    body = t.call("PATCH", f"{_BS}/bs-1")["json"]
    expected = BriefState.model_validate(state).model_dump()
    assert json.loads(body["brief"]) == expected
    t.on("GET", f"{_BS}/bs-1", _row(id="bs-1", brief=body["brief"]))
    session = _run(CoreHttpGateway(t).get_brainstorm_session(owner_sub="alice", session_id="bs-1"))
    assert session is not None and session.brief == expected


def test_create_brainstorm_session_records_owner_email_and_reads_it_back():
    t = FakeTransport()
    t.on("POST", _BS, _row(owner_email="a@b.com"))
    s = _run(
        CoreHttpGateway(t).create_brainstorm_session(
            owner_sub="alice",
            target="t",
            geography=None,
            problem=None,
            thread_id="th-1",
            owner_email="a@b.com",
        )
    )
    assert t.call("POST", _BS)["json"]["owner_email"] == "a@b.com"
    assert s.owner_email == "a@b.com"
