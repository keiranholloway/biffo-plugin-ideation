"""Absolute path to this plugin's manifest, and the reads everything else makes
of it — shared by the plugin, its scripts and its tests.

Resolution has two cases, mirroring ``admin_app.py``'s ``_resolve_static_dir``
(same env var, same reason):

* **Deployed, behind the shared plugin host (ADR-0021).** ``deploy-app.yml``'s
  "Package and deploy the shared plugin host" step copies this plugin's
  ``src/`` directly to the Lambda task root, but places the manifest at
  ``services/ideation/biffo.plugin.json`` — a *sibling* of the flattened
  ``src/``, not an ancestor of it. No amount of walking up from this module's
  own location ever reaches it. ``BIFFO_PLUGINS_ROOT`` is the anchor the host
  already sets for exactly this (``discover_plugins()``'s own manifest scan
  reads it the same way), so when it's present we build the path from it
  directly: ``BIFFO_PLUGINS_ROOT/ideation/biffo.plugin.json``.
* **Local — this repo checkout, local dev, or this module's own tests.**
  ``BIFFO_PLUGINS_ROOT`` isn't set, so we fall back to walking up from this
  module looking for ``biffo.plugin.json`` sitting alongside the plugin's own
  source (here, the repo root).

Before this, the walk-up ran unconditionally and never found the manifest
under the deployed layout above — ``MANIFEST_PATH`` resolved to a nonexistent
path, and because ``app.py`` calls :func:`manifest_required_group` at *module
import time*, the ``FileNotFoundError`` crashed the whole Lambda at cold start,
not just one request (issue #173).

:func:`manifest_required_group` lives here rather than in any one consumer
because the required-group literal is what this plugin keeps getting wrong. The
manifest declares it once per surface and the shared plugin host enforces
exactly that field; every hand-maintained second copy of it has, sooner or
later, 403'd the very caller a manifest change was meant to admit — issue #163
(``app.py``), then issue #171 (the chat-agent seed payload, at a *different*
enforcement point). One function, called by every consumer, is what stops there
being a next one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _resolve_manifest_path(plugins_root: str | None = None) -> Path:
    if plugins_root:
        return Path(plugins_root) / "ideation" / "biffo.plugin.json"

    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "biffo.plugin.json"
        if candidate.is_file():
            return candidate
    return here.parent.parent / "biffo.plugin.json"


MANIFEST_PATH = _resolve_manifest_path(os.environ.get("BIFFO_PLUGINS_ROOT"))


def manifest_required_group(surface: str) -> str:
    """The group ``<surface>.required_group`` declares in ``biffo.plugin.json``.

    ``surface`` is a manifest ingress key — ``"user_ingress"`` or
    ``"admin_ingress"``. Read from the manifest rather than hardcoded, so no
    consumer can drift from the field the shared plugin host's own group gate
    reads before it ever dispatches a request (ADR-0018 §2).

    Raises ``KeyError`` on an unknown surface or a surface that declares no
    group — failing closed and loudly at import time, rather than quietly
    admitting or refusing the wrong audience.
    """
    return json.loads(MANIFEST_PATH.read_text())[surface]["required_group"]
