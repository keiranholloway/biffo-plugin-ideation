"""What the Ideation Engine is *actually* running on — defaults included.

The two prompts are constants in :mod:`ideation.definitions`. The two models
are **not** symmetrical, and the difference is the whole point of this module:

- The **analyst** model genuinely falls back to the built-in below.
  ``IdeationService.finalise`` reads the stored row live (``get_own_config``)
  and uses :func:`analysis_model` only when there is no row.
- The **challenger** model has no such fallback. The plugin sends Core no model
  at all (see ``adapter.run_chat_turn``); with ``chat_agents_dynamic: true`` in
  the manifest, Core resolves the model from the stored chat-agent row and has
  nothing to resolve when that row is missing — a chat turn 404s rather than
  running on a default (``scripts/seed_chat_agents.py``'s docstring says so).
  So :func:`chat_model` is a **seed value**, not a runtime fallback: it is what
  a seed/"store a copy" write would put *into* the row, and it never reaches a
  request.

This module used to report both as "the model in use, from the built-in
default", which was true of neither once a row existed and was never true of
the challenger (issue #67). Setting ``IDEATION_CHAT_MODEL`` would have changed
what the admin panel claimed was running without changing what ran.
:func:`effective_models` therefore takes the stored rows and resolves against
them; it cannot be called without deciding what is stored.

This is still the single place the defaults are named, so the things that must
agree provably do: what ``scripts/seed_chat_agents.py`` would store, what
:mod:`ideation.app` falls back to for the analyst, and what the admin panel
shows.

The agent payloads carry ``system_prompt``. That is fine here and only here:
every caller of this module is admin-gated (``admin_app.require_admin``), which
is the same audience Core's own ``/chat-agents`` admin routes already return
prompt text to. ADR-0016 §1's rule is that an *unprivileged* caller never sees
it — see ``app.list_agents``, which still returns keys and names only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from .definitions import (
    ANALYST_AGENT_NAME,
    ANALYST_INSTRUCTIONS,
    CHALLENGER_AGENT_NAME,
    CHALLENGER_INSTRUCTIONS,
)

#: Role names as the stored chat-agent rows spell them.
CHALLENGER_ROLE = "challenger"
ANALYST_ROLE = "analyst"

#: The environment variables that override the built-in model choices, and the
#: values used when they are unset. Nothing in this deployment sets either var.
#: ``IDEATION_CHAT_MODEL`` only changes what a *seed* would write (see the module
#: docstring); ``IDEATION_ANALYSIS_MODEL`` is a real runtime fallback.
CHAT_MODEL_ENV = "IDEATION_CHAT_MODEL"
ANALYSIS_MODEL_ENV = "IDEATION_ANALYSIS_MODEL"
DEFAULT_CHAT_MODEL = "anthropic/claude-sonnet-4"
# ``:online`` is OpenRouter's web-search suffix: the provider runs the search and
# injects the results, so the analyst researches for real without this deployment
# needing a Brave credential. It is in the *default* deliberately — competitive
# research is the point of the analyst, and an environment that silently falls
# back to the model's parametric recall invents competitors and their URLs.
# Costs $0.001–$0.005 per analysis run on top of tokens.
#
# The slug is dotted: ``claude-opus-4.8``. It was ``claude-opus-4-8`` here, which
# is not a model OpenRouter serves (it is absent from all 367 in its /models
# list), so every analysis run was made against a nonexistent model while the
# challenger's valid ``claude-sonnet-4`` kept working — which is why chat ran and
# only the report was broken.
DEFAULT_ANALYSIS_MODEL = "anthropic/claude-opus-4.8:online"

#: ``source`` values on the payloads below — where a value actually came from.
#: ``stored``/``unconfigured`` are facts about the chat-agent table; the other
#: three are only reachable where a built-in fallback genuinely exists, or where
#: the table could not be read at all.
SOURCE_BUILT_IN = "built-in"
SOURCE_ENV = "env"
#: A stored row is what runs — the built-in below is not consulted.
SOURCE_STORED = "stored"
#: Nothing is stored and there is no fallback: the request path fails.
SOURCE_UNCONFIGURED = "unconfigured"
#: The stored rows could not be read, so no honest claim can be made.
SOURCE_UNKNOWN = "unknown"


def chat_model() -> str:
    """The model a *seed* of the challenger row would store — NOT a fallback.

    Nothing sends this to Core. With ``chat_agents_dynamic: true`` the stored
    row is the only source of the challenger's model, so this value reaches a
    request only by having been written into that row (by
    ``scripts/seed_chat_agents.py``, or the panel's "store a copy to edit").
    """
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


StoredAgents = Sequence[Mapping[str, Any]] | None


def _stored_challenger(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The row Core resolves for a session that pinned no explicit challenger.

    Matched by ``agent_key``, not by role: ``IdeationService.start_session``
    pins ``CHALLENGER_AGENT_NAME`` when the founder picks nothing, and Core's
    chat-turn spine resolves by key. A founder who *did* pick another persona
    runs on that row's model instead — which is why the payload names the key
    it resolved rather than claiming to be the only challenger model in play.
    """
    return next((r for r in rows if r.get("agent_key") == CHALLENGER_AGENT_NAME), None)


def _stored_analyst(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The row ``IdeationService.finalise`` reads via ``get_own_config``.

    Keyed by *role*, not agent_key, because that read is
    ``GET /internal/plugins/me/config/analyst``. Only active rows are
    considered; Core's tie-break when several are active is Core's, not
    reproduced here.
    """
    return next((r for r in rows if r.get("role") == ANALYST_ROLE and r.get("active")), None)


def effective_models(stored_agents: StoredAgents) -> list[dict[str, Any]]:
    """The models the engine is using right now, resolved against what is stored.

    ``stored_agents`` is the chat-agent table as Core returns it, or ``None``
    when it could not be read — in which case every entry is reported as
    ``unknown`` rather than falling back to a claim about built-ins. The
    argument is required precisely so a caller cannot re-create the old bug of
    answering this question without looking (issue #67).

    Deliberately *not* the model catalog: the catalog is the admin-curated list
    of choices a model is picked *from*; these are what a request actually runs
    on. Each entry also carries ``builtin_model_id`` — what a seed or a "store a
    copy" write would put in the row — so the panel can show the choice and the
    default side by side without the two drifting.
    """
    unknown = stored_agents is None
    rows = list(stored_agents or ())
    challenger = None if unknown else _stored_challenger(rows)
    analyst = None if unknown else _stored_analyst(rows)

    return [
        _chat_entry(unknown=unknown, row=challenger),
        _analysis_entry(unknown=unknown, row=analyst),
    ]


def _chat_entry(*, unknown: bool, row: Mapping[str, Any] | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "purpose": "chat",
        "label": "Challenger (requirement-gathering chat)",
        "agent_key": CHALLENGER_AGENT_NAME,
        "env_var": CHAT_MODEL_ENV,
        "env_var_is_runtime_fallback": False,
        "builtin_model_id": chat_model(),
    }
    if unknown:
        return {
            **entry,
            "model_id": None,
            "source": SOURCE_UNKNOWN,
            "detail": (
                "Could not read the stored chat-agent rows from Core, so the model "
                "actually in use is unknown. It is whatever the stored "
                f"{CHALLENGER_AGENT_NAME} row says."
            ),
        }
    if row is None:
        return {
            **entry,
            "model_id": None,
            "source": SOURCE_UNCONFIGURED,
            "detail": (
                f"No stored {CHALLENGER_AGENT_NAME} row. chat_agents_dynamic is on, so "
                "Core has nothing to resolve and every chat turn fails until one is "
                f"seeded — {CHAT_MODEL_ENV} and the built-in below do not fill the gap, "
                "they only decide what a seed would write."
            ),
        }
    return {
        **entry,
        "model_id": row.get("model"),
        "source": SOURCE_STORED,
        "detail": (
            f"From the stored {CHALLENGER_AGENT_NAME} row, which is the only source — "
            "the plugin sends Core no model on a chat turn. Editing this agent on the "
            "Chat Agents tab is what changes it."
        ),
    }


def _analysis_entry(*, unknown: bool, row: Mapping[str, Any] | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "purpose": "analysis",
        "label": "Analyst (PRD + viability scorecard)",
        "agent_key": ANALYST_AGENT_NAME,
        "env_var": ANALYSIS_MODEL_ENV,
        "env_var_is_runtime_fallback": True,
        "builtin_model_id": analysis_model(),
    }
    if unknown:
        return {
            **entry,
            "model_id": None,
            "source": SOURCE_UNKNOWN,
            "detail": (
                "Could not read the stored chat-agent rows from Core, so it is unknown "
                "whether the analyst is running on a stored row or on the built-in "
                "default below."
            ),
        }
    if row is not None:
        return {
            **entry,
            "model_id": row.get("model"),
            "source": SOURCE_STORED,
            "detail": (
                f"From the stored active {ANALYST_ROLE} row ({row.get('agent_key')}), which "
                "finalise() reads live on every run. The built-in default below is not "
                "consulted while this row exists."
            ),
        }
    return {
        **entry,
        "model_id": analysis_model(),
        "source": _model_source(ANALYSIS_MODEL_ENV),
        "detail": (
            f"No stored active {ANALYST_ROLE} row, so finalise() falls back to this "
            "plugin's own value. Storing a row overrides it."
        ),
    }
