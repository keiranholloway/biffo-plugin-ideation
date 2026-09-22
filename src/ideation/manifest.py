"""Absolute path to this plugin's manifest, and the reads everything else makes
of it — shared by the plugin, its scripts and its tests.

Mirrors the plugin-template's ``manifest.py``: walk up from this module to find
``biffo.plugin.json``, so it resolves in both the repo layout (manifest at the
plugin root) and the deployed Lambda (manifest bundled at the task root).

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
from pathlib import Path


def _resolve_manifest_path() -> Path:
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "biffo.plugin.json"
        if candidate.is_file():
            return candidate
    return here.parent.parent / "biffo.plugin.json"


MANIFEST_PATH = _resolve_manifest_path()


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
