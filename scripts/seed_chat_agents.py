#!/usr/bin/env python3
"""Seed the ideation-challenger and ideation-analyst rows into Core's live
chat-agent registry.

This is now a manual, operator-driven entry point, **not a hard prerequisite**
(issue #93). Both plugin apps (``ideation.app`` and ``ideation.admin_app``)
seed the same two rows automatically on every cold start, insert-if-absent, via
``POST /internal/plugins/me/config/seed``. This script exists for the same
reason ``biffo-plugin-idea-scout``'s manual seed script does: an operator with
real Cognito admin credentials can run it ahead of time (e.g. before the
plugin's first deploy, or to inspect/dry-run the payload) without waiting on a
cold start, and it uses the admin-bearer-token route (``POST
/admin/plugins/ideation/chat-agents``) because a human operator has no SigV4
identity to seed with — 409 on an already-seeded role is treated as success.

Before issue #93, this really was a hard prerequisite: with
``chat_agents_dynamic: true`` and no automatic seeding, an unrun script left
every founder chat turn 404ing, and — contrary to what this docstring used to
claim — the analyst was no safer: ``IdeationService.finalise()`` no longer
falls back to the built-in default when its row is absent; it raises
``AgentConfigMissingError``. Both roles are equally a deployment-ordering
hazard if nothing ever seeds them; automatic startup seeding is what removes
that hazard now, not this script.

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

from ideation.effective_config import builtin_chat_agents  # noqa: E402

_PLUGIN_NAME = "ideation"


def _builtin(role: str) -> dict:
    """The built-in default for one role — the single source those defaults are
    named in (``ideation.effective_config``), so seeding stores a copy of what
    is already running rather than a second, drifting definition of it."""
    return next(agent for agent in builtin_chat_agents() if agent["role"] == role)


def build_payload() -> dict:
    """The exact challenger seed row — must match today's hardcoded static
    registration (biffo.plugin.json's chat_agents entry) so cutover changes
    nothing observable for founders."""
    return _builtin("challenger")


def build_analyst_payload() -> dict:
    """The exact analyst seed row — must match today's hardcoded
    ANALYST_INSTRUCTIONS/model so cutover changes nothing observable."""
    return _builtin("analyst")


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
