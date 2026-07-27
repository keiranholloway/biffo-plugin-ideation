"""The admin-facing ASGI app (ADR-0021 admin_ingress): endpoints + auth gating.

The gate (``require_admin``) and the Core request proxy (``_core_request``) are
overridden so the app is exercised over a fake Core — the JWT verification is
covered elsewhere (the SDK); this tests routing, auth-gating, and status-codes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ideation.admin_app import app, require_admin


@pytest.fixture
def core_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def client(core_mock: AsyncMock) -> Iterator[TestClient]:
    """Override require_admin to return a fake admin, and _core_request to use
    the mock so we can assert on calls without a real HTTP transport."""
    app.dependency_overrides[require_admin] = lambda: ForwardedUser(
        sub="admin-1", groups=["admin"], token="fake-admin-token"
    )

    async def fake_core_request(
        method: str, path: str, *, admin: ForwardedUser, json: dict[str, Any] | None = None
    ) -> Any:
        """Replace the real httpx call with a mock."""
        return await core_mock(method, path, admin=admin, json=json)

    # Patch the admin_app._core_request directly
    import ideation.admin_app

    original_core_request = ideation.admin_app._core_request
    ideation.admin_app._core_request = fake_core_request

    yield TestClient(app)

    # Restore
    app.dependency_overrides.clear()
    ideation.admin_app._core_request = original_core_request


class TestChatAgentsRoutes:
    """Test all 5 chat-agent routes."""

    def test_list_chat_agents(self, client: TestClient, core_mock: AsyncMock) -> None:
        core_mock.return_value = [{"key": "agent-1", "name": "Agent 1"}]

        resp = client.get("/chat-agents")

        assert resp.status_code == 200
        assert resp.json() == [{"key": "agent-1", "name": "Agent 1"}]
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "GET"
        assert "/api/v1/admin/plugins/ideation/chat-agents" in call_args[0][1]

    def test_create_chat_agent(self, client: TestClient, core_mock: AsyncMock) -> None:
        created_agent = {"key": "agent-2", "name": "Agent 2"}
        core_mock.return_value = created_agent

        resp = client.post("/chat-agents", json={"key": "agent-2", "name": "Agent 2"})

        assert resp.status_code == 201
        assert resp.json() == created_agent
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "POST"
        assert "/api/v1/admin/plugins/ideation/chat-agents" in call_args[0][1]

    def test_get_chat_agent(self, client: TestClient, core_mock: AsyncMock) -> None:
        agent = {"key": "agent-1", "name": "Agent 1"}
        core_mock.return_value = agent

        resp = client.get("/chat-agents/agent-1")

        assert resp.status_code == 200
        assert resp.json() == agent
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "GET"
        assert "agent-1" in call_args[0][1]

    def test_update_chat_agent(self, client: TestClient, core_mock: AsyncMock) -> None:
        updated_agent = {"key": "agent-1", "name": "Updated Name"}
        core_mock.return_value = updated_agent

        resp = client.put("/chat-agents/agent-1", json={"key": "agent-1", "name": "Updated Name"})

        assert resp.status_code == 200
        assert resp.json() == updated_agent
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "PUT"
        assert "agent-1" in call_args[0][1]

    def test_delete_chat_agent(self, client: TestClient, core_mock: AsyncMock) -> None:
        core_mock.return_value = None

        resp = client.delete("/chat-agents/agent-1")

        assert resp.status_code == 204
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "DELETE"
        assert "agent-1" in call_args[0][1]


class TestModelCatalogIsNotProxiedHere:
    """The model catalog is a manifest-declared api_route: Core serves it and
    the plugin host forwards it (biffo-template#684). This app used to proxy it
    by calling its *public* path — which resolves to the plugin host, so the
    host called itself and forwarded on to Core. Three hops for a one-hop
    request, and every one of them able to cold-start (biffo-template#652).
    """

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/model-catalog"),
            ("post", "/model-catalog"),
            ("get", "/model-catalog/1"),
            ("put", "/model-catalog/1"),
            ("delete", "/model-catalog/1"),
        ],
    )
    def test_no_model_catalog_route_is_served(
        self, client: TestClient, core_mock: AsyncMock, method: str, path: str
    ) -> None:
        resp = getattr(client, method)(path) if method in ("get", "delete") else None
        if resp is None:
            resp = getattr(client, method)(path, json={})

        assert resp.status_code == 404
        core_mock.assert_not_called()

    def test_the_self_calling_public_base_is_gone(self) -> None:
        """The base that pointed back at the host's own public path is removed,
        not merely unused — leaving it invites the next proxy route to reuse it."""
        import ideation.admin_app

        assert not hasattr(ideation.admin_app, "_MODEL_CATALOG_BASE")
        # The one base still proxied resolves to Core directly (no /plugins/
        # segment for API Gateway's catch-all to claim).
        assert not ideation.admin_app._CHAT_AGENTS_BASE.startswith("/api/v1/plugins/")


class TestAuthGating:
    """Test that routes are properly gated by the admin group."""

    def test_routes_require_admin_group_without_override(self) -> None:
        """When no dependency override is applied, require_admin runs for real,
        and without Cognito env, it rejects the request with 401."""
        app.dependency_overrides.clear()
        monkeypatched = TestClient(app, raise_server_exceptions=False)

        # All 5 proxied routes should reject with 401
        assert monkeypatched.get("/chat-agents").status_code == 401
        assert monkeypatched.post("/chat-agents", json={}).status_code == 401
        assert monkeypatched.get("/chat-agents/key").status_code == 401
        assert monkeypatched.put("/chat-agents/key", json={}).status_code == 401
        assert monkeypatched.delete("/chat-agents/key").status_code == 401


class TestCoreRequestTimeout:
    """``_core_request``'s timeout is chosen here, not inherited from httpx.

    A bare ``httpx.AsyncClient()`` applies httpx's own 5s default. Core
    cold-starts in ~4.3s of init before running a line of handler, so that
    unchosen default expires on precisely the requests that most need it — and
    an expired client raises, surfacing as a 500 with no upstream status to
    explain it (biffo-template#652).
    """

    def _run(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        import ideation.admin_app

        captured: dict[str, Any] = {}

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        class RecordingClient(httpx.AsyncClient):
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)
                super().__init__(transport=httpx.MockTransport(respond), **kwargs)

        monkeypatch.setattr(ideation.admin_app.httpx, "AsyncClient", RecordingClient)
        monkeypatch.setattr(ideation.admin_app, "_CORE_API_URL", "https://core.test")

        admin = ForwardedUser(sub="admin-1", groups=["admin"], token="fake-admin-token")
        result = asyncio.run(ideation.admin_app._core_request("GET", "/anything", admin=admin))
        assert result == {"ok": True}
        return captured

    def test_passes_an_explicit_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert "timeout" in self._run(monkeypatch), (
            "no timeout was passed, so httpx's own 5s default applies — shorter "
            "than Core's cold start"
        )

    def test_the_timeout_outlasts_a_core_cold_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        timeout = httpx.Timeout(self._run(monkeypatch)["timeout"])

        # 30s matches biffo_plugin_sdk's BiffoAPIClient default, and leaves room
        # over the ~4.9s cold start measured in CloudWatch.
        assert timeout.read is not None and timeout.read >= 30.0
        assert timeout.connect is not None and timeout.connect >= 30.0


class TestCoreErrorHandling:
    """Test that _core_request errors are surfaced as HTTP exceptions."""

    def test_core_404_surfaces_as_404(self, client: TestClient, core_mock: AsyncMock) -> None:
        from fastapi import HTTPException

        async def failing_core_request(  # type: ignore[no-untyped-def]
            *args: Any, **kwargs: Any
        ) -> Any:
            raise HTTPException(status_code=404, detail="Not found")

        import ideation.admin_app

        original = ideation.admin_app._core_request
        ideation.admin_app._core_request = failing_core_request

        resp = client.get("/chat-agents/nope")
        assert resp.status_code == 404

        ideation.admin_app._core_request = original

    def test_core_500_surfaces_as_500(self, client: TestClient, core_mock: AsyncMock) -> None:
        from fastapi import HTTPException

        async def failing_core_request(  # type: ignore[no-untyped-def]
            *args: Any, **kwargs: Any
        ) -> Any:
            raise HTTPException(status_code=500, detail="Internal server error")

        import ideation.admin_app

        original = ideation.admin_app._core_request
        ideation.admin_app._core_request = failing_core_request

        resp = client.get("/chat-agents")
        assert resp.status_code == 500

        ideation.admin_app._core_request = original


def test_no_identity_route_the_admin_ui_now_uses_the_portals_well_known_document() -> None:
    """The admin UI resolves its Cognito identity from the portal's public
    /.well-known/biffo-identity.json (same origin, unauthenticated static
    content) instead of a self-served /identity route. That route used to
    exist here, but was a dead end even for same-origin callers: both the API
    Gateway's JWT authorizer and the plugin host's group_gate sit in front of
    this app, so it could never be reached before a session exists to prove
    admin-group membership with — confirmed live, a direct fetch 401'd."""
    app.dependency_overrides.clear()
    client = TestClient(app)

    resp = client.get("/identity")

    assert resp.status_code == 404


def test_exposes_an_asgi_app_not_a_lambda_handler() -> None:
    """The admin app, like the founder app, is a FastAPI ASGI app (not a
    Mangum handler) — the shared plugin host provides the Lambda entrypoint."""
    import ideation.admin_app as app_module

    assert isinstance(app_module.app, FastAPI)
    assert not hasattr(app_module, "handler")


class TestResolveStaticDir:
    """The deployed Lambda flattens src/ into its own task root, one directory
    shallower than this source checkout — a single fixed relative-parent count
    can't resolve both shapes (the bug this pins: web-admin/dist was never
    found in production because the old fixed computation pointed outside the
    deployed package entirely)."""

    def test_uses_plugins_root_when_set(self) -> None:
        from ideation.admin_app import _resolve_static_dir

        result = _resolve_static_dir("/var/task/services")
        assert result == Path("/var/task/services/ideation/web-admin/dist")

    def test_falls_back_to_source_relative_path_when_unset(self) -> None:
        from ideation.admin_app import _resolve_static_dir

        result = _resolve_static_dir(None)
        # <repo-root>/src/ideation/admin_app.py -> <repo-root>/web-admin/dist
        assert result.name == "dist"
        assert result.parent.name == "web-admin"
        assert (result.parent.parent / "src" / "ideation" / "admin_app.py").is_file()

    def test_falls_back_when_plugins_root_is_empty_string(self) -> None:
        from ideation.admin_app import _resolve_static_dir

        result = _resolve_static_dir("")
        assert result.name == "dist"
        assert "var/task" not in str(result)
