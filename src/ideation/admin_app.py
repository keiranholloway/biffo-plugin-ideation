"""The Ideation Engine's admin-facing ASGI app (ADR-0021 admin_ingress).

A FastAPI app mounted by the shared plugin host at
``/api/v1/plugins/ideation/admin/*`` — admin-gated (both by the host's own
group-gate and, defence-in-depth, this app's own require_group("admin"),
mirroring app.py's founder-facing convention). Proxies Core's admin routes
for chat-agent management as same-origin routes, reports the engine's
effective configuration, and serves the built web-admin/ bundle.

**``/effective-config`` is not a proxy.** Every other route here lists a
table, and an empty table rendered as "not configured" — which was false,
because the engine runs on the built-ins in :mod:`ideation.effective_config`
until an admin stores a row over one (issue #58). It answers from this
plugin's own code and environment, so it reaches neither Core nor the
database.

**The model catalog is not proxied here.** Its five CRUD routes are declared
in ``biffo.plugin.json``'s ``api_routes``, which means Core generates and
serves them and the plugin host forwards them to Core itself
(biffo-template#684, core >=0.136.0), authorised by the table's own ADR-0004
``permissions`` (admin on every operation). This app used to proxy them by
calling their public path — but that path resolves back to the host, so the
host was calling itself and then forwarding on to Core: three hops, two of
them cold-startable, for a request Core answers in one (biffo-template#652).
The admin UI calls ``/api/v1/plugins/ideation/model-catalog`` directly.

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

from .effective_config import builtin_chat_agents, effective_models

require_admin = require_group("admin")

_CORE_API_URL = os.environ.get("BIFFO_CORE_API_URL", "")
_PLUGIN_NAME = "ideation"
_CHAT_AGENTS_BASE = f"/api/v1/admin/plugins/{_PLUGIN_NAME}/chat-agents"

#: How long to wait on Core. Explicit, and matching the ``biffo_plugin_sdk``
#: ``BiffoAPIClient`` default: a bare ``httpx.AsyncClient()`` silently carries
#: httpx's own 5s default that nobody here chose, and Core cold-starts in ~4.3s
#: of init before it runs a line of handler — so the unchosen default expires on
#: exactly the requests that most need it, surfacing as a 500 with no upstream
#: status to explain it (biffo-template#652).
_CORE_TIMEOUT_SECONDS = 30.0

app = FastAPI(title="Ideation Engine Admin", docs_url=None, redoc_url=None)


async def _core_request(
    method: str, path: str, *, admin: ForwardedUser, json: dict[str, Any] | None = None
) -> Any:
    """Forward one call to Core, authenticated as the calling admin (not this
    plugin's own service principal — see module docstring)."""
    url = f"{_CORE_API_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=_CORE_TIMEOUT_SECONDS) as client:
        resp = await client.request(
            method, url, json=json, headers={"Authorization": f"Bearer {admin.token}"}
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json() if resp.content else None


# ── effective configuration ──────────────────────────────────────────────────


@app.get("/effective-config")
async def read_effective_config(
    admin: ForwardedUser = Depends(require_admin),
) -> dict[str, Any]:
    """What the engine is running on right now, whether or not it is stored.

    The other routes here list *tables*. On an empty table that reads as "not
    configured", which is false for the analyst: it runs on the built-ins in
    :mod:`ideation.effective_config`, and creating a row **overrides** one of
    them rather than filling a void (issue #58). This route is what lets the
    admin UI say so.

    ``agents`` is still answered with no hop — it is this plugin's own
    constants. ``models`` is not: the challenger's model comes *only* from its
    stored row, and the analyst's comes from its stored row whenever one
    exists, so answering from constants alone reported a model that nothing was
    running on (issue #67). That costs one Core read.

    The property the old no-hop version bought — this route cannot fail on a
    cold Core — is kept explicitly instead of by not asking: a failed read
    yields ``source: "unknown"``, never a 5xx. An admin panel that cannot say
    what is in use is bad; one that shows an error page instead of the built-in
    prompts is worse.
    """
    stored = await _stored_agents(admin)
    return {"agents": builtin_chat_agents(), "models": effective_models(stored)}


async def _stored_agents(admin: ForwardedUser) -> list[dict[str, Any]] | None:
    """The stored chat-agent rows, or ``None`` if Core could not be read.

    ``None`` is not "no rows" — it is "we do not know", and
    :func:`effective_models` renders the two differently on purpose. Collapsing
    a failed read into an empty list would report "nothing is stored, chat is
    broken" every time Core cold-started.
    """
    try:
        rows = await _core_request("GET", _CHAT_AGENTS_BASE, admin=admin)
    except Exception:
        return None
    return list(rows) if isinstance(rows, list) else None


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


# ── model catalog: deliberately not here (see the module docstring) ──────────
#
# ``/model-catalog`` and ``/model-catalog/{id}`` are manifest-declared
# ``api_routes``. Core serves them and the plugin host forwards them; the admin
# UI calls ``/api/v1/plugins/ideation/model-catalog`` directly rather than a
# proxy on this app. tests/test_admin_app.py pins that they stay absent here,
# and tests/test_manifest.py pins that the manifest still declares them.


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
