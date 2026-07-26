"""The admin-facing ASGI app (ADR-0021 admin_ingress): endpoints + auth gating.

The gate (``require_admin``) and the Core request proxy (``_core_request``) are
overridden so the app is exercised over a fake Core — the JWT verification is
covered elsewhere (the SDK); this tests routing, auth-gating, and status-codes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

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


class TestModelCatalogRoutes:
    """Test all 5 model-catalog routes."""

    def test_list_model_catalog(self, client: TestClient, core_mock: AsyncMock) -> None:
        core_mock.return_value = [{"id": "1", "model_id": "gpt-4", "label": "GPT-4"}]

        resp = client.get("/model-catalog")

        assert resp.status_code == 200
        assert resp.json() == [{"id": "1", "model_id": "gpt-4", "label": "GPT-4"}]
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "GET"
        assert "/api/v1/plugins/ideation/model-catalog" in call_args[0][1]

    def test_create_model_catalog_entry(self, client: TestClient, core_mock: AsyncMock) -> None:
        entry = {"id": "1", "model_id": "gpt-4", "label": "GPT-4"}
        core_mock.return_value = entry

        resp = client.post("/model-catalog", json={"model_id": "gpt-4", "label": "GPT-4"})

        assert resp.status_code == 201
        assert resp.json() == entry
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "POST"
        assert "/api/v1/plugins/ideation/model-catalog" in call_args[0][1]

    def test_get_model_catalog_entry(self, client: TestClient, core_mock: AsyncMock) -> None:
        entry = {"id": "1", "model_id": "gpt-4", "label": "GPT-4"}
        core_mock.return_value = entry

        resp = client.get("/model-catalog/1")

        assert resp.status_code == 200
        assert resp.json() == entry
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "GET"
        assert "1" in call_args[0][1]

    def test_update_model_catalog_entry(self, client: TestClient, core_mock: AsyncMock) -> None:
        updated_entry = {"id": "1", "model_id": "gpt-4", "label": "GPT-4-Updated"}
        core_mock.return_value = updated_entry

        resp = client.put("/model-catalog/1", json={"model_id": "gpt-4", "label": "GPT-4-Updated"})

        assert resp.status_code == 200
        assert resp.json() == updated_entry
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "PUT"
        assert "1" in call_args[0][1]

    def test_delete_model_catalog_entry(self, client: TestClient, core_mock: AsyncMock) -> None:
        core_mock.return_value = None

        resp = client.delete("/model-catalog/1")

        assert resp.status_code == 204
        core_mock.assert_called_once()
        call_args = core_mock.call_args
        assert call_args[0][0] == "DELETE"
        assert "1" in call_args[0][1]


class TestAuthGating:
    """Test that routes are properly gated by the admin group."""

    def test_routes_require_admin_group_without_override(self) -> None:
        """When no dependency override is applied, require_admin runs for real,
        and without Cognito env, it rejects the request with 401."""
        app.dependency_overrides.clear()
        monkeypatched = TestClient(app, raise_server_exceptions=False)

        # All 10 routes should reject with 401
        assert monkeypatched.get("/chat-agents").status_code == 401
        assert monkeypatched.post("/chat-agents", json={}).status_code == 401
        assert monkeypatched.get("/chat-agents/key").status_code == 401
        assert monkeypatched.put("/chat-agents/key", json={}).status_code == 401
        assert monkeypatched.delete("/chat-agents/key").status_code == 401

        assert monkeypatched.get("/model-catalog").status_code == 401
        assert monkeypatched.post("/model-catalog", json={}).status_code == 401
        assert monkeypatched.get("/model-catalog/id").status_code == 401
        assert monkeypatched.put("/model-catalog/id", json={}).status_code == 401
        assert monkeypatched.delete("/model-catalog/id").status_code == 401


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


class TestIdentityRoute:
    """Test the /identity route that serves pool/client info for the admin UI."""

    def test_identity_route_returns_cognito_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The /identity route requires no auth and returns pool/client/region."""

        monkeypatch.setenv("BIFFO_COGNITO_USER_POOL_ID", "us-east-1_test123")
        monkeypatch.setenv("BIFFO_COGNITO_CLIENT_ID", "test-client-456")
        monkeypatch.setenv("BIFFO_COGNITO_REGION", "us-east-1")

        # No dependency override — /identity should work without auth
        app.dependency_overrides.clear()
        client = TestClient(app)

        resp = client.get("/identity")

        assert resp.status_code == 200
        data = resp.json()
        assert data["userPoolId"] == "us-east-1_test123"
        assert data["clientId"] == "test-client-456"
        assert data["region"] == "us-east-1"

    def test_identity_route_handles_missing_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env vars are missing, /identity returns empty strings (no crash)."""
        monkeypatch.delenv("BIFFO_COGNITO_USER_POOL_ID", raising=False)
        monkeypatch.delenv("BIFFO_COGNITO_CLIENT_ID", raising=False)
        monkeypatch.delenv("BIFFO_COGNITO_REGION", raising=False)

        app.dependency_overrides.clear()
        client = TestClient(app)

        resp = client.get("/identity")

        assert resp.status_code == 200
        data = resp.json()
        assert data["userPoolId"] == ""
        assert data["clientId"] == ""
        assert data["region"] == ""


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
