#!/usr/bin/env python3
"""Seed the ideation-challenger and ideation-analyst rows into Core's live
chat-agent registry.

Run this ONCE, manually, by an operator with real Cognito admin credentials,
BEFORE deploying biffo.plugin.json's chat_agents_dynamic: true flag. Once that
flag is live, Core stops registering ideation-challenger from the static
manifest — if no row exists yet in the dynamic table, every founder chat turn
404s until this has run. This script does not run itself automatically; it is
not invoked by any deploy pipeline or plugin runtime code.

The analyst row is seeded here too, even though the analyst was never part of
Core's static chat-agent registry (it sends its whole definition inline on
every run, not resolved server-side by agent_key) — IdeationService.finalise()
reads this row live via the internal plugin-config read (ADR-0009) to make the
analyst's prompt/model admin-editable, falling back to the built-in default
if this row is absent (so it is NOT a deployment-ordering hazard the way the
challenger row is — finalise() degrades gracefully, chat turns don't 404).

Usage:
    CORE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com \
    ADMIN_BEARER_TOKEN=<a real Cognito admin id/access token> \
    python scripts/seed_chat_agents.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))

from ideation.definitions import (  # noqa: E402
    ANALYST_AGENT_NAME,
    ANALYST_INSTRUCTIONS,
    CHALLENGER_AGENT_NAME,
    CHALLENGER_INSTRUCTIONS,
)

_PLUGIN_NAME = "ideation"
_DEFAULT_CHAT_MODEL = os.environ.get("IDEATION_CHAT_MODEL", "anthropic/claude-sonnet-4")
_DEFAULT_ANALYSIS_MODEL = os.environ.get("IDEATION_ANALYSIS_MODEL", "anthropic/claude-opus-4-8")


def build_payload() -> dict:
    """The exact challenger seed row — must match today's hardcoded static
    registration (biffo.plugin.json's chat_agents entry) so cutover changes
    nothing observable for founders."""
    return {
        "agent_key": CHALLENGER_AGENT_NAME,
        "agent_name": CHALLENGER_AGENT_NAME,
        "role": "challenger",
        "system_prompt": CHALLENGER_INSTRUCTIONS,
        "model": _DEFAULT_CHAT_MODEL,
        "required_group": "founder",
        "active": True,
    }


def build_analyst_payload() -> dict:
    """The exact analyst seed row — must match today's hardcoded
    ANALYST_INSTRUCTIONS/model so cutover changes nothing observable."""
    return {
        "agent_key": ANALYST_AGENT_NAME,
        "agent_name": ANALYST_AGENT_NAME,
        "role": "analyst",
        "system_prompt": ANALYST_INSTRUCTIONS,
        "model": _DEFAULT_ANALYSIS_MODEL,
        "required_group": "founder",
        "active": True,
    }


def _seed_one(payload: dict, *, core_api_url: str, admin_token: str) -> bool:
    """POST one payload; True on success (created or already-seeded), False on
    a real failure."""
    url = f"{core_api_url.rstrip('/')}/api/v1/admin/plugins/{_PLUGIN_NAME}/chat-agents"
    resp = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {admin_token}"})

    if resp.status_code == 409:
        print(
            f"Agent {payload['agent_key']!r} already exists for plugin {_PLUGIN_NAME!r} — "
            "nothing to do (already seeded).",
        )
        return True
    if resp.status_code >= 400:
        print(
            f"Seed failed for {payload['agent_key']!r}: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
        return False

    print(f"Seeded {payload['agent_key']!r}: {resp.json()}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the payloads without sending them."
    )
    args = parser.parse_args()

    payloads = [build_payload(), build_analyst_payload()]

    if args.dry_run:
        import json

        print(json.dumps(payloads, indent=2))
        return 0

    core_api_url = os.environ.get("CORE_API_URL")
    admin_token = os.environ.get("ADMIN_BEARER_TOKEN")
    if not core_api_url or not admin_token:
        print(
            "CORE_API_URL and ADMIN_BEARER_TOKEN must both be set (or use --dry-run).",
            file=sys.stderr,
        )
        return 1

    # A list comprehension (not a generator into all()) so a failure on the
    # challenger doesn't short-circuit and skip attempting the analyst too.
    results = [_seed_one(p, core_api_url=core_api_url, admin_token=admin_token) for p in payloads]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
