"""What the Ideation Engine is *actually* running on — defaults included.

The engine's effective configuration does not live in a table. The two prompts
are constants in :mod:`ideation.definitions`; the two models are read from the
environment with a hardcoded fallback; and both the challenger's registration
and the analyst's live config fall back to those built-ins when no row exists
(``IdeationService.finalise``'s ``get_own_config`` read, and Core's chat-agent
resolution respectively).

That fallback is deliberate. What was not deliberate is that the admin panel
listed the *table* and therefore reported "No agents defined yet" while these
values drove every request — accurate about the table, and actively misleading
about the system (issue #58). Storing a row does not *add* configuration to an
empty system; it **overrides** one of the defaults below.

This module is the single place those defaults are named, so three things that
must agree provably do: what :mod:`ideation.app` hands the service, what
``scripts/seed_chat_agents.py`` would store, and what the admin panel shows.

The agent payloads carry ``system_prompt``. That is fine here and only here:
every caller of this module is admin-gated (``admin_app.require_admin``), which
is the same audience Core's own ``/chat-agents`` admin routes already return
prompt text to. ADR-0016 §1's rule is that an *unprivileged* caller never sees
it — see ``app.list_agents``, which still returns keys and names only.
"""

from __future__ import annotations

import os
from typing import Any

from .definitions import (
    ANALYST_AGENT_NAME,
    ANALYST_INSTRUCTIONS,
    CHALLENGER_AGENT_NAME,
    CHALLENGER_INSTRUCTIONS,
)

#: The environment variables that override the built-in model choices, and the
#: values used when they are unset. These are the literal defaults that have
#: been running in dev: nothing sets the env vars, so nothing stores them either.
CHAT_MODEL_ENV = "IDEATION_CHAT_MODEL"
ANALYSIS_MODEL_ENV = "IDEATION_ANALYSIS_MODEL"
DEFAULT_CHAT_MODEL = "anthropic/claude-sonnet-4"
DEFAULT_ANALYSIS_MODEL = "anthropic/claude-opus-4-8"

#: ``source`` values on the payloads below — where a value actually came from.
SOURCE_BUILT_IN = "built-in"
SOURCE_ENV = "env"


def chat_model() -> str:
    """The model every requirement-gathering challenger turn runs on."""
    return os.environ.get(CHAT_MODEL_ENV) or DEFAULT_CHAT_MODEL


def analysis_model() -> str:
    """The model the analyst runs on when no admin-configured row overrides it."""
    return os.environ.get(ANALYSIS_MODEL_ENV) or DEFAULT_ANALYSIS_MODEL


def _model_source(env_var: str) -> str:
    return SOURCE_ENV if os.environ.get(env_var) else SOURCE_BUILT_IN


def builtin_chat_agents() -> list[dict[str, Any]]:
    """The two agents the engine falls back to with an empty chat-agent table.

    Byte-for-byte what ``scripts/seed_chat_agents.py`` posts, because that
    script builds its payloads from this function — a stored row must be a copy
    of the default it replaces, not a second, drifting definition of it.
    """
    return [
        {
            "agent_key": CHALLENGER_AGENT_NAME,
            "agent_name": CHALLENGER_AGENT_NAME,
            "role": "challenger",
            "system_prompt": CHALLENGER_INSTRUCTIONS,
            "model": chat_model(),
            "required_group": "founder",
            "active": True,
        },
        {
            "agent_key": ANALYST_AGENT_NAME,
            "agent_name": ANALYST_AGENT_NAME,
            "role": "analyst",
            "system_prompt": ANALYST_INSTRUCTIONS,
            "model": analysis_model(),
            "required_group": "founder",
            "active": True,
        },
    ]


def effective_models() -> list[dict[str, Any]]:
    """The models the engine is using right now, and where each came from.

    Deliberately *not* the model catalog: the catalog is an admin-curated list
    of choices, and nothing in the request path reads it. These two values are
    what actually reaches the runtime, so an empty catalog must show them as
    inherited rather than showing nothing.
    """
    return [
        {
            "purpose": "chat",
            "label": "Challenger (requirement-gathering chat)",
            "model_id": chat_model(),
            "source": _model_source(CHAT_MODEL_ENV),
            "env_var": CHAT_MODEL_ENV,
        },
        {
            "purpose": "analysis",
            "label": "Analyst (PRD + viability scorecard)",
            "model_id": analysis_model(),
            "source": _model_source(ANALYSIS_MODEL_ENV),
            "env_var": ANALYSIS_MODEL_ENV,
        },
    ]
