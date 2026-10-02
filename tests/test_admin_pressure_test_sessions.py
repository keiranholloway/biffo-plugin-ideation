"""Admin all-users Pressure Test sessions: list, detail, cost breakdown, gating."""

from __future__ import annotations

import json
from typing import Any

import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

from ideation.adapter import CoreNotFoundError
from ideation.admin_app import app, get_admin_transport, require_admin

ROOT = "/api/v1/internal"
SESS = f"{ROOT}/owner-data-admin/ideation_sessions"
REPORTS = f"{ROOT}/owner-data-admin/ideation_reports"
RUNS = f"{ROOT}/agent-runs"


def _row(sid: str, owner: str, **over: Any) -> dict[str, Any]:
    row = {
        "id": sid,
        "owner_sub": owner,
        "owner_email": None,
        "status": "complete",
        "title": f"title {sid}",
        "seed_idea": f"idea {sid}",
        "thread_id": f"th-{sid}",
        "turn_count": 2,
        "analysis_run_id": f"{sid}-an",
        "created_at": "2026-01-01T00:00:00",
        "deleted": False,
    }
    row.update(over)
    return row


def _run(rid: str, cost: float | None, model: str = "m1") -> dict[str, Any]:
    return {
        "id": rid,
        "agent_name": "x",
        "model": model,
        "status": "completed",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": cost,
    }


class FakeCore:
    def __init__(self) -> None:
        self.sessions = [
            _row("a", "sub-alice", owner_email="alice@x.com", created_at="2026-01-02T00:00:00"),
            _row("b", "sub-bob", status="gathering", created_at="2026-01-03T00:00:00"),
            _row("c", "sub-alice", owner_email="alice@x.com", deleted=True),
        ]
        self.runs: dict[str, dict[str, Any]] = {}
        self.thread_runs: dict[str, list[str]] = {}
        for sid, costs in {"a": (0.5, 0.25, 0.25), "b": (None, None, None), "c": (1, 1, 1)}.items():
            self.thread_runs[f"th-{sid}"] = [f"{sid}-t1", f"{sid}-t2"]
            self.runs[f"{sid}-t1"] = _run(f"{sid}-t1", costs[0])
            self.runs[f"{sid}-t2"] = _run(f"{sid}-t2", costs[1])
            self.runs[f"{sid}-an"] = _run(f"{sid}-an", costs[2], model="analyst-model")

    async def request(self, method, path, *, json=None, params=None):  # noqa: A002
        if path == SESS:
            off = (params or {}).get("offset", 0)
            return self.sessions[off : off + (params or {}).get("limit", 100)]
        if path.startswith(SESS + "/"):
            sid = path.rsplit("/", 1)[1]
            for r in self.sessions:
                if r["id"] == sid:
                    return r
            raise CoreNotFoundError("404")
        if path == REPORTS:
            return [
                {
                    "session_id": params["session_id"],
                    "prd": '{"title": "The PRD"}',
                    "scorecard": '{"viability": 4}',
                    "model": "analyst-model",
                }
            ]
        if path.endswith("/usage") and method == "GET":
            tid = path.split("/")[-2]
            return {"runs": [self.runs[r] for r in self.thread_runs.get(tid, [])]}
        if path == f"{RUNS}/usage":
            return {"runs": [self.runs[r] for r in (json or {})["run_ids"]]}
        if path.endswith("/messages"):
            return {
                "messages": [
                    {"role": "system", "content": "hidden"},
                    {"role": "user", "content": "my idea"},
                    {"role": "assistant", "content": "why now?"},
                ]
            }
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def core() -> FakeCore:
    return FakeCore()


@pytest.fixture
def client(core: FakeCore):
    app.dependency_overrides[require_admin] = lambda: ForwardedUser(
        sub="admin", groups=["admin"], token="t"
    )
    app.dependency_overrides[get_admin_transport] = lambda: core
    yield TestClient(app)
    app.dependency_overrides.clear()


def _by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["session_id"]: s for s in body["sessions"]}


def test_list_returns_sessions_from_two_owners(client: TestClient) -> None:
    body = client.get("/pressure-test/sessions").json()
    assert {s["owner_sub"] for s in body["sessions"]} == {"sub-alice", "sub-bob"}


def test_list_email_unknown_and_deleted_marked(client: TestClient) -> None:
    s = _by_id(client.get("/pressure-test/sessions").json())
    assert s["a"]["owner_display"] == "alice@x.com" and s["a"]["owner_email_known"]
    assert s["b"]["owner_display"] == "sub-bob" and not s["b"]["owner_email_known"]
    assert s["c"]["deleted"] is True and s["a"]["deleted"] is False


def test_filter_and_sort(client: TestClient) -> None:
    ids = lambda q: [s["session_id"] for s in client.get(q).json()["sessions"]]  # noqa: E731
    assert set(ids("/pressure-test/sessions?user=alice")) == {"a", "c"}
    assert ids("/pressure-test/sessions?status=gathering") == ["b"]
    assert ids("/pressure-test/sessions?sort=cost&order=desc") == ["c", "a", "b"]
    assert client.get("/pressure-test/sessions?sort=nope").status_code == 422


def test_list_cost_totals_priced_and_flags_unpriced(client: TestClient) -> None:
    s = _by_id(client.get("/pressure-test/sessions").json())
    assert s["a"]["cost"]["total_cost_usd"] == 1.0 and s["a"]["cost"]["runs"] == 3
    assert s["b"]["cost"]["total_cost_usd"] is None
    assert s["b"]["cost"]["unpriced_runs"] == 3


def test_detail_has_transcript_report_and_cost(client: TestClient, core: FakeCore) -> None:
    core.runs["a-t2"]["cost_usd"] = None
    d = client.get("/pressure-test/sessions/a").json()
    assert d["seed_idea"] == "idea a"
    assert d["transcript"] == [
        {"role": "user", "content": "my idea"},
        {"role": "assistant", "content": "why now?"},
    ]
    assert d["report"] == {
        "prd": {"title": "The PRD"},
        "scorecard": {"viability": 4},
        "model": "analyst-model",
    }
    rows = d["cost"]["rows"]
    assert [r["stage"] for r in rows] == ["chat", "chat", "analysis"]
    assert rows[2]["model"] == "analyst-model"
    assert rows[1]["priced"] is False and rows[1]["cost_usd"] is None
    assert d["cost"]["total_cost_usd"] == 0.75
    assert d["cost"]["unpriced_runs"] == 1


def test_analyst_run_on_thread_is_counted_once(client: TestClient, core: FakeCore) -> None:
    core.thread_runs["th-a"].append("a-an")
    d = client.get("/pressure-test/sessions/a").json()
    assert d["cost"]["runs"] == 3 and d["cost"]["total_cost_usd"] == 1.0


def test_detail_without_report_and_unknown(client: TestClient, core: FakeCore) -> None:
    orig = core.request

    async def req(method, path, **kw):
        if path == REPORTS:
            return []
        return await orig(method, path, **kw)

    core.request = req  # type: ignore[method-assign]
    assert client.get("/pressure-test/sessions/b").json()["report"] is None
    assert client.get("/pressure-test/sessions/nope").status_code == 404


@pytest.mark.parametrize("path", ["/pressure-test/sessions", "/pressure-test/sessions/a"])
def test_non_admin_gets_403(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    app.dependency_overrides.clear()
    monkeypatch.setenv("BIFFO_COGNITO_USER_POOL_ID", "pool-x")
    monkeypatch.setenv("BIFFO_COGNITO_REGION", "eu-west-1")
    monkeypatch.setenv("BIFFO_COGNITO_CLIENT_ID", "client-y")
    import biffo_plugin_sdk._cognito as cognito

    monkeypatch.setattr(
        cognito,
        "verify_cognito_jwt",
        lambda token, **_: {"sub": "u", "cognito:groups": ["founder"]},
    )
    resp = TestClient(app).get(path, headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 403
