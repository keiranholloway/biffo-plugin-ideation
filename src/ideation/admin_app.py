"""The Ideation Engine's admin-facing ASGI app (ADR-0021 admin_ingress).

A FastAPI app mounted by the shared plugin host at
``/api/v1/plugins/ideation/admin/*`` — admin-gated (both by the host's own
group-gate and, defence-in-depth, this app's own require_group("admin"),
mirroring app.py's founder-facing convention). Proxies Core's admin routes
for chat-agent and model-catalog management as same-origin routes, and
(once web-admin/ has a built UI — a later milestone) serves that static
bundle too.

Unlike app.py's founder-facing CoreTransport (SigV4-signed as this plugin's
own service principal, forwarding a founder token for dual-auth), these Core
routes only need the calling admin's own real Cognito token forwarded as-is
— require_admin (Core-side) just checks it's a valid, admin-group token, no
service-principal auth involved. So this app talks to Core with a plain
httpx client, not the SDK's SignedCoreClient.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from biffo_plugin_sdk import ForwardedUser, require_group
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

require_admin = require_group("admin")

_CORE_API_URL = os.environ.get("BIFFO_CORE_API_URL", "")
_PLUGIN_NAME = "ideation"
_CHAT_AGENTS_BASE = f"/api/v1/admin/plugins/{_PLUGIN_NAME}/chat-agents"
_MODEL_CATALOG_BASE = f"/api/v1/plugins/{_PLUGIN_NAME}/model-catalog"

app = FastAPI(title="Ideation Engine Admin", docs_url=None, redoc_url=None)


async def _core_request(
    method: str, path: str, *, admin: ForwardedUser, json: dict[str, Any] | None = None
) -> Any:
    """Forward one call to Core, authenticated as the calling admin (not this
    plugin's own service principal — see module docstring)."""
    url = f"{_CORE_API_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method, url, json=json, headers={"Authorization": f"Bearer {admin.token}"}
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json() if resp.content else None


# ── chat agents ──────────────────────────────────────────────────────────────


@app.get("/chat-agents")
async def list_chat_agents(admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", _CHAT_AGENTS_BASE, admin=admin)


@app.post("/chat-agents", status_code=201)
async def create_chat_agent(
    body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("POST", _CHAT_AGENTS_BASE, admin=admin, json=body)


@app.get("/chat-agents/{agent_key}")
async def get_chat_agent(agent_key: str, admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin)


@app.put("/chat-agents/{agent_key}")
async def update_chat_agent(
    agent_key: str, body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("PUT", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin, json=body)


@app.delete("/chat-agents/{agent_key}", status_code=204)
async def delete_chat_agent(agent_key: str, admin: ForwardedUser = Depends(require_admin)) -> None:
    await _core_request("DELETE", f"{_CHAT_AGENTS_BASE}/{agent_key}", admin=admin)


# ── model catalog ────────────────────────────────────────────────────────────


@app.get("/model-catalog")
async def list_model_catalog(admin: ForwardedUser = Depends(require_admin)) -> Any:
    return await _core_request("GET", _MODEL_CATALOG_BASE, admin=admin)


@app.post("/model-catalog", status_code=201)
async def create_model_catalog_entry(
    body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("POST", _MODEL_CATALOG_BASE, admin=admin, json=body)


@app.get("/model-catalog/{entry_id}")
async def get_model_catalog_entry(
    entry_id: str, admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("GET", f"{_MODEL_CATALOG_BASE}/{entry_id}", admin=admin)


@app.put("/model-catalog/{entry_id}")
async def update_model_catalog_entry(
    entry_id: str, body: dict[str, Any], admin: ForwardedUser = Depends(require_admin)
) -> Any:
    return await _core_request("PUT", f"{_MODEL_CATALOG_BASE}/{entry_id}", admin=admin, json=body)


@app.delete("/model-catalog/{entry_id}", status_code=204)
async def delete_model_catalog_entry(
    entry_id: str, admin: ForwardedUser = Depends(require_admin)
) -> None:
    await _core_request("DELETE", f"{_MODEL_CATALOG_BASE}/{entry_id}", admin=admin)


# ── static admin UI (mount conditionally so this app works before the UI is ──
# ── built, e.g. in this milestone's own tests) ────────────────────────────────


def _resolve_static_dir(plugins_root: str | None) -> Path:
    """Where the built web-admin/dist actually lands, in either context.

    The deployed plugin-host Lambda flattens this package's src/ into its own
    task root (biffo-platform's deploy-app.yml "Package and deploy the shared
    plugin host" step: `cp -r "$plugin_dir"/src/. "$pkg/"`), so this file ends
    up at <task-root>/ideation/admin_app.py — one directory shallower than in
    this source checkout (<repo>/src/ideation/admin_app.py). A single fixed
    relative parent count can't resolve correctly in both shapes.
    ``BIFFO_PLUGINS_ROOT`` (already set on the Lambda for
    discover_plugins()'s own manifest scan) is the deployed anchor instead:
    the same deploy step copies this plugin's built web-admin/dist to
    services/ideation/web-admin/dist alongside the manifest, so
    ``BIFFO_PLUGINS_ROOT/ideation/web-admin/dist`` is where it actually
    lands. Falls back to the source-repo-relative path (this file's own
    location) when the env var isn't set, e.g. local dev or this app's own
    tests.
    """
    if plugins_root:
        return Path(plugins_root) / "ideation" / "web-admin" / "dist"
    return Path(__file__).resolve().parent.parent.parent / "web-admin" / "dist"


_STATIC_DIR = _resolve_static_dir(os.environ.get("BIFFO_PLUGINS_ROOT"))
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="admin-ui")
