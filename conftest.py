"""Ensures `from scripts.<module> import ...` resolves under both this
repo's own pytest run (governed by pyproject.toml's ``pythonpath``) and
biffo-platform's aggregate monorepo run once vendored there (governed by the
platform repo root's pyproject.toml, which has no such setting and never
sees this directory's own config). conftest.py files are collected
unconditionally along the path to every test below them, so this runs first
either way.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
