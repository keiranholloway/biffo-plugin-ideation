"""Regression guard for the chat-agent seed script.

The seed migration produces a row matching today's actual hardcoded prompt/model
exactly (a literal diff, not just 'a row exists'). Since there's no real
migration (this is a manual script, not a migration), the test instead pins
build_payload()'s exact output to today's frozen static registration.
"""

from __future__ import annotations

from ideation.definitions import (
    ANALYST_AGENT_NAME,
    ANALYST_INSTRUCTIONS,
    CHALLENGER_AGENT_NAME,
    CHALLENGER_INSTRUCTIONS,
)
from ideation.manifest import manifest_required_group
from scripts.seed_chat_agents import build_analyst_payload, build_payload

#: What the seeded rows must demand. Read from the manifest, not named here:
#: these assertions used to pin the literal ``"founder"`` *as correct*, which is
#: why the seed payload kept it through two fixes of the same defect elsewhere
#: (issue #171). Pinning the literal made the guard a second copy of the bug.
_REQUIRED_GROUP = manifest_required_group("user_ingress")


def test_seed_payload_matches_the_current_static_challenger_config() -> None:
    payload = build_payload()
    assert payload["agent_key"] == CHALLENGER_AGENT_NAME == "ideation-challenger"
    assert payload["system_prompt"] == CHALLENGER_INSTRUCTIONS
    assert payload["role"] == "challenger"
    assert payload["required_group"] == _REQUIRED_GROUP
    assert payload["active"] is True


def test_analyst_seed_payload_matches_the_current_hardcoded_analyst_config() -> None:
    payload = build_analyst_payload()
    assert payload["agent_key"] == ANALYST_AGENT_NAME == "ideation-analyst"
    assert payload["system_prompt"] == ANALYST_INSTRUCTIONS
    assert payload["role"] == "analyst"
    assert payload["required_group"] == _REQUIRED_GROUP
    assert payload["active"] is True


def test_the_seeded_group_is_the_group_the_manifest_admits() -> None:
    """Issue #171. The seeded ``required_group`` is what Core checks on every
    chat turn (``internal_agent_chat.py``), and seeding never overwrites — so if
    it disagrees with the group the manifest lets through the front door, every
    admitted caller is 403'd on their first message, permanently, for that
    tenant.

    Stated as the equality above *and* as the concrete value, so this fails
    loudly rather than silently agreeing with itself if both sides drift
    together.
    """
    assert _REQUIRED_GROUP == "admin"  # owner decision B, biffo-platform-app#70
    for payload in (build_payload(), build_analyst_payload()):
        assert payload["required_group"] == "admin", payload["agent_key"]
