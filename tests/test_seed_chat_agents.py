"""Regression guard for the chat-agent seed script.

The seed migration produces a row matching today's actual hardcoded prompt/model
exactly (a literal diff, not just 'a row exists'). Since there's no real
migration (this is a manual script, not a migration), the test instead pins
build_payload()'s exact output to today's frozen static registration.
"""

from __future__ import annotations

from seed_chat_agents import build_payload  # type: ignore[reportMissingImports]

from ideation.definitions import CHALLENGER_AGENT_NAME, CHALLENGER_INSTRUCTIONS


def test_seed_payload_matches_the_current_static_challenger_config() -> None:
    payload = build_payload()
    assert payload["agent_key"] == CHALLENGER_AGENT_NAME == "ideation-challenger"
    assert payload["system_prompt"] == CHALLENGER_INSTRUCTIONS
    assert payload["role"] == "challenger"
    assert payload["required_group"] == "founder"
    assert payload["active"] is True
