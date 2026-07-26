"""Pytest configuration for ideation tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Make scripts/ importable for tests like test_seed_chat_agents
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
