"""Admin all-users Brain-Storm sessions: list, detail, cost breakdown, gating."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

from ideation.adapter import CoreNotFoundError
from ideation.admin_app import app, get_admin_transport, require_admin
from ideation.claims import email_from_token

ROOT = "/api/v1/internal"
SESS = f"{ROOT}/owner-data-admin/brainstorm_sessions"
OPPS = f"{ROOT}/owner-data-admin/brainstorm_opportunities"
RUNS = f"{ROOT}/agent-runs"


def _row(sid: str, owner: str, **over: Any) -> dict[str, Any]:
    row = {
        "id": sid,
        "owner_sub": owner,
        "owner_email": None,
        "status": "complete",
        "title": f"title {sid}",
        "thread_id": f"th-{sid}",
        "turn_count": 2,
        "research_run_ids": json.dumps([f"{sid}-r1"]),
        "synthesis_run_id": f"{sid}-syn",
        "created_at": "2026-01-01T00:00:00",
        "deleted": False,
    }
    row.update(over)
    return row


def _run(rid: str, cost: float | None, model: str = "m1", name: str = "agent") -> dict[str, Any]:
    return {
        "id": rid,
        "agent_name": name,
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
            _row("b", "sub-bob", status="failed", created_at="2026-01-03T00:00:00"),
            _row("c", "sub-alice", owner_email="alice@x.com", deleted=True),
        ]
        self.runs: dict[str, dict[str, Any]] = {}
        self.thread_runs: dict[str, list[str]] = {}
        for sid, costs in {"a": (0.5, 0.25, 0.25), "b": (None, None, None), "c": (1, 1, 1)}.items():
            self.thread_runs[f"th-{sid}"] = [f"{sid}-t1"]
            self.runs[f"{sid}-t1"] = _run(f"{sid}-t1", costs[0], name="qualifier")
            self.runs[f"{sid}-r1"] = _run(f"{sid}-r1", costs[1], name="market")
            self.runs[f"{sid}-syn"] = _run(f"{sid}-syn", costs[2], name="synthesis")
        self.calls: list[tuple[str, str]] = []

    async def request(self, method, path, *, json=None, params=None):  # noqa: A002
        self.calls.append((method, path))
        if path == SESS:
            off = (params or {}).get("offset", 0)
            return self.sessions[off : off + (params or {}).get("limit", 100)]
        if path.startswith(SESS + "/"):
            sid = path.rsplit("/", 1)[1]
            for r in self.sessions:
                if r["id"] == sid:
                    return r
            raise CoreNotFoundError("404")
        if path == OPPS:
            return [
                {
                    "id": "o2",
                    "owner_sub": "sub-alice",
                    "session_id": params["session_id"],
                    "rank": 2,
                    "title": "second",
                    "pitch": "p2",
                },
                {
                    "id": "o1",
                    "owner_sub": "sub-alice",
                    "session_id": params["session_id"],
                    "rank": 1,
                    "title": "first",
                    "pitch": "p1",
                },
            ]
        if path.endswith("/usage") and method == "GET":
            tid = path.split("/")[-2]
            return {"runs": [self.runs[r] for r in self.thread_runs.get(tid, [])]}
        if path == f"{RUNS}/usage":
            return {"runs": [self.runs[r] for r in json["run_ids"]]}
        if path.endswith("/messages"):
            return {
                "messages": [
                    {"role": "system", "content": "hidden"},
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "what market?"},
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
    body = client.get("/sessions").json()
    owners = {s["owner_sub"] for s in body["sessions"]}
    assert owners == {"sub-alice", "sub-bob"}


def test_list_shows_email_or_says_unknown(client: TestClient) -> None:
    s = _by_id(client.get("/sessions").json())
    assert s["a"]["owner_display"] == "alice@x.com" and s["a"]["owner_email_known"]
    assert s["b"]["owner_display"] == "sub-bob" and not s["b"]["owner_email_known"]


def test_deleted_session_appears_and_is_marked(client: TestClient) -> None:
    s = _by_id(client.get("/sessions").json())
    assert s["c"]["deleted"] is True and s["a"]["deleted"] is False


def test_filter_by_user_and_status(client: TestClient) -> None:
    assert set(_by_id(client.get("/sessions?user=alice").json())) == {"a", "c"}
    assert set(_by_id(client.get("/sessions?user=sub-bob").json())) == {"b"}
    assert set(_by_id(client.get("/sessions?status=failed").json())) == {"b"}


def test_sort_by_date_and_cost(client: TestClient) -> None:
    ids = lambda q: [s["session_id"] for s in client.get(q).json()["sessions"]]  # noqa: E731
    assert ids("/sessions?sort=date&order=desc") == ["b", "a", "c"]
    assert ids("/sessions?sort=date&order=asc") == ["c", "a", "b"]
    # c = 3.0, a = 1.0, b unpriced -> always last
    assert ids("/sessions?sort=cost&order=desc") == ["c", "a", "b"]
    assert ids("/sessions?sort=cost&order=asc") == ["a", "c", "b"]


def test_list_cost_totals_priced_and_flags_unpriced(client: TestClient) -> None:
    s = _by_id(client.get("/sessions").json())
    assert s["a"]["cost"]["total_cost_usd"] == 1.0 and s["a"]["cost"]["unpriced_runs"] == 0
    assert s["b"]["cost"]["total_cost_usd"] is None  # never 0
    assert s["b"]["cost"]["unpriced_runs"] == 3


def test_bad_sort_is_422(client: TestClient) -> None:
    assert client.get("/sessions?sort=nope").status_code == 422


def test_detail_has_transcript_opportunities_and_cost_breakdown(
    client: TestClient, core: FakeCore
) -> None:
    core.runs["a-r1"]["cost_usd"] = None  # one unpriced research run
    d = client.get("/sessions/a").json()
    assert d["transcript"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "what market?"},
    ]
    assert [o["title"] for o in d["opportunities"]] == ["first", "second"]
    rows = d["cost"]["rows"]
    assert [r["stage"] for r in rows] == ["qualifying", "research", "synthesis"]
    assert rows[0]["model"] == "m1" and rows[0]["input_tokens"] == 10
    assert rows[1]["cost_usd"] is None and rows[1]["priced"] is False
    assert d["cost"]["total_cost_usd"] == 0.75  # priced runs only
    assert d["cost"]["unpriced_runs"] == 1


def test_detail_deleted_session_is_readable_and_marked(client: TestClient) -> None:
    d = client.get("/sessions/c").json()
    assert d["deleted"] is True


def test_detail_unknown_is_404(client: TestClient) -> None:
    assert client.get("/sessions/nope").status_code == 404


def test_run_on_thread_and_pipeline_is_counted_once(client: TestClient, core: FakeCore) -> None:
    core.thread_runs["th-a"].append("a-syn")
    d = client.get("/sessions/a").json()
    assert d["cost"]["runs"] == 3 and d["cost"]["total_cost_usd"] == 1.0


def test_usage_failure_does_not_sink_the_list(client: TestClient, core: FakeCore) -> None:
    orig = core.request

    async def flaky(method, path, **kw):
        if path.endswith("th-a/usage"):
            raise RuntimeError("boom")
        return await orig(method, path, **kw)

    core.request = flaky  # type: ignore[method-assign]
    s = _by_id(client.get("/sessions").json())
    assert s["a"]["cost_error"] is True and s["a"]["cost"] is None
    assert s["b"]["cost_error"] is False


@pytest.mark.parametrize("path", ["/sessions", "/sessions/a"])
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


def _jwt(claims: dict[str, Any]) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def test_email_from_token() -> None:
    assert email_from_token(_jwt({"sub": "s", "email": "a@b.com"})) == "a@b.com"
    assert email_from_token(_jwt({"sub": "s"})) is None
    assert email_from_token("not-a-jwt") is None
    assert email_from_token("") is None
