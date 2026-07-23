"""Absolute path to this plugin's manifest, shared by the plugin and its tests.

Mirrors the plugin-template's ``manifest.py``: walk up from this module to find
``biffo.plugin.json``, so it resolves in both the repo layout (manifest at the
plugin root) and the deployed Lambda (manifest bundled at the task root).
"""

from __future__ import annotations

from pathlib import Path


def _resolve_manifest_path() -> Path:
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "biffo.plugin.json"
        if candidate.is_file():
            return candidate
    return here.parent.parent / "biffo.plugin.json"


MANIFEST_PATH = _resolve_manifest_path()
