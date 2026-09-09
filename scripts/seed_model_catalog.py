#!/usr/bin/env python3
"""Seed the initial OpenRouter model catalog into the admin-managed
ideation_model_catalog table.

Run this ONCE, manually, by an operator with real Cognito admin credentials.
Unlike scripts/seed_chat_agents.py, this table has no deployment-ordering
hazard — it's a new table with no live behavior depending on it yet — but it
still needs a real admin token, since ideation_model_catalog's generic CRUD
(Core's ADR-0004 plugin_router, /api/v1/plugins/ideation/model-catalog) is
gated to the admin role on every operation.

The exact model ids/prices below were confirmed live against OpenRouter's own
GET https://openrouter.ai/api/v1/models at the time this was written — that
catalog shifts monthly, so re-check before relying on this list staying
accurate; the admin UI (once built) lets an operator add/remove entries
without touching this script again.

Each plain model id is paired with a ``:online`` sibling (issue #92) so the
catalog can tell an admin which entries actually let a search-dependent agent
search — OpenRouter's own suffix, not re-verified per model here (see the
issue's "Not verified" section); ``web_capable`` is set explicitly on each row
rather than derived from the id at read time.

Usage:
    CORE_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com \
    ADMIN_BEARER_TOKEN=<a real Cognito admin id/access token> \
    python scripts/seed_model_catalog.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

_PLUGIN_NAME = "ideation"

#: OpenRouter's generic web-search suffix (issue #92) — appending it to any
#: model id turns on provider-run web search for that model. ``web_capable``
#: is declared explicitly on each seed row rather than computed at read time
#: (see biffo.plugin.json's column description), but it must still agree with
#: this suffix for every seeded row, which ``tests/test_seed_model_catalog.py``
#: pins.
ONLINE_SUFFIX = ":online"


def _online_variant(model: dict[str, object]) -> dict[str, object]:
    """The web-capable sibling of a plain seed model.

    Paired rather than hand-duplicated so the ``:online`` id, the
    "WEB-CONNECTED" label and the ``web_capable`` flag can never drift apart
    from the base entry they describe. Never the catalog default — a default
    an agent silently inherits should not carry a live-search cost per call.
    """
    return {
        "model_id": f"{model['model_id']}{ONLINE_SUFFIX}",
        "label": f"{model['label']} — WEB-CONNECTED ({ONLINE_SUFFIX}, live search; "
        "use for research/analyst agents)",
        "active": True,
        "is_default": False,
        "web_capable": True,
    }


# Cheapest solid option first (the default); the named "kimi-k3" example is
# included but is NOT the cheapest available — live pricing put it at roughly
# the same tier as Claude Sonnet 5, not the budget end of the catalog.
#
# Each plain model is paired with its ``:online`` sibling (issue #92): before
# this, the catalog had no way to tell an admin which entries let a
# search-dependent agent (the ideation analyst) actually search, so picking
# one of the plain five for that role silently ran it without web access.
_BASE_SEED_MODELS: list[dict[str, object]] = [
    {
        "model_id": "deepseek/deepseek-v4-flash",
        "label": "DeepSeek V4 Flash (cheapest, solid tool use)",
        "active": True,
        "is_default": True,
        "web_capable": False,
    },
    {
        "model_id": "qwen/qwen3.6-flash",
        "label": "Qwen3.6 Flash (cheap, agentic)",
        "active": True,
        "is_default": False,
        "web_capable": False,
    },
    {
        "model_id": "z-ai/glm-5.1",
        "label": "GLM 5.1 (mid-tier, strong agentic coding)",
        "active": True,
        "is_default": False,
        "web_capable": False,
    },
    {
        "model_id": "moonshotai/kimi-k3",
        "label": "Kimi K3 (long-horizon agentic, premium-tier pricing)",
        "active": True,
        "is_default": False,
        "web_capable": False,
    },
    {
        "model_id": "anthropic/claude-sonnet-5",
        "label": "Claude Sonnet 5 (premium quality anchor)",
        "active": True,
        "is_default": False,
        "web_capable": False,
    },
]

_SEED_MODELS: list[dict[str, object]] = [
    entry for model in _BASE_SEED_MODELS for entry in (model, _online_variant(model))
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the payloads without sending them."
    )
    args = parser.parse_args()

    if args.dry_run:
        print(json.dumps(_SEED_MODELS, indent=2))
        return 0

    core_api_url = os.environ.get("CORE_API_URL")
    admin_token = os.environ.get("ADMIN_BEARER_TOKEN")
    if not core_api_url or not admin_token:
        print(
            "CORE_API_URL and ADMIN_BEARER_TOKEN must both be set (or use --dry-run).",
            file=sys.stderr,
        )
        return 1

    url = f"{core_api_url.rstrip('/')}/api/v1/plugins/{_PLUGIN_NAME}/model-catalog"
    headers = {"Authorization": f"Bearer {admin_token}"}
    failures = 0
    for model in _SEED_MODELS:
        resp = httpx.post(url, json=model, headers=headers)
        if resp.status_code >= 400:
            print(
                f"Seed failed for {model['model_id']!r}: {resp.status_code} {resp.text}",
                file=sys.stderr,
            )
            failures += 1
            continue
        print(f"Seeded {model['model_id']!r}: {resp.json()}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
