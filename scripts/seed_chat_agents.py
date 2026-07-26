#!/usr/bin/env python3
"""Seed the ideation-challenger row into Core's live chat-agent registry.

Run this ONCE, manually, by an operator with real Cognito admin credentials,
BEFORE deploying biffo.plugin.json's chat_agents_dynamic: true flag. Once that
flag is live, Core stops registering ideation-challenger from the static
manifest — if no row exists yet in the dynamic table, every founder chat turn
404s until this has run. This script does not run itself automatically; it is
not invoked by any deploy pipeline or plugin runtime code.

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

from ideation.definitions import CHALLENGER_AGENT_NAME, CHALLENGER_INSTRUCTIONS  # noqa: E402

_PLUGIN_NAME = "ideation"
_DEFAULT_MODEL = os.environ.get("IDEATION_CHAT_MODEL", "anthropic/claude-sonnet-4")


def build_payload() -> dict:
    """The exact seed row — must match today's hardcoded static registration
    (biffo.plugin.json's chat_agents entry) so cutover changes nothing
    observable for founders."""
    return {
        "agent_key": CHALLENGER_AGENT_NAME,
        "agent_name": CHALLENGER_AGENT_NAME,
        "role": "challenger",
        "system_prompt": CHALLENGER_INSTRUCTIONS,
        "model": _DEFAULT_MODEL,
        "required_group": "founder",
        "active": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the payload without sending it."
    )
    args = parser.parse_args()

    payload = build_payload()

    if args.dry_run:
        import json

        print(json.dumps(payload, indent=2))
        return 0

    core_api_url = os.environ.get("CORE_API_URL")
    admin_token = os.environ.get("ADMIN_BEARER_TOKEN")
    if not core_api_url or not admin_token:
        print(
            "CORE_API_URL and ADMIN_BEARER_TOKEN must both be set (or use --dry-run).",
            file=sys.stderr,
        )
        return 1

    url = f"{core_api_url.rstrip('/')}/api/v1/admin/plugins/{_PLUGIN_NAME}/chat-agents"
    resp = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {admin_token}"})

    if resp.status_code == 409:
        print(
            f"Agent {payload['agent_key']!r} already exists for plugin {_PLUGIN_NAME!r} — "
            "nothing to do (already seeded).",
        )
        return 0
    if resp.status_code >= 400:
        print(f"Seed failed: {resp.status_code} {resp.text}", file=sys.stderr)
        return 1

    print(f"Seeded {payload['agent_key']!r}: {resp.json()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
