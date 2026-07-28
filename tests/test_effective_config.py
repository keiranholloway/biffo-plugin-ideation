"""The effective configuration the engine actually runs on (issue #58).

The admin panel used to list the chat-agent table and report "No agents defined
yet" on an empty one — true about the table, false about the system, which was
running on the built-ins pinned here. These tests hold the three views of those
defaults together: what ``ideation.app`` hands the service, what the seed script
would store, and what the admin panel is told.
"""

from __future__ import annotations

import pytest

from ideation import app as founder_app
from ideation.definitions import (
    ANALYST_AGENT_NAME,
    ANALYST_INSTRUCTIONS,
    CHALLENGER_AGENT_NAME,
    CHALLENGER_INSTRUCTIONS,
)
from ideation.effective_config import (
    ANALYSIS_MODEL_ENV,
    CHAT_MODEL_ENV,
    DEFAULT_ANALYSIS_MODEL,
    DEFAULT_CHAT_MODEL,
    SOURCE_BUILT_IN,
    SOURCE_ENV,
    analysis_model,
    builtin_chat_agents,
    chat_model,
    effective_models,
)


class TestBuiltinAgents:
    def test_both_agents_the_engine_falls_back_to_are_reported(self) -> None:
        """An empty chat-agent table does not mean an unconfigured engine: these
        two are what drives every request until an admin overrides them."""
        agents = builtin_chat_agents()

        assert [a["agent_key"] for a in agents] == [CHALLENGER_AGENT_NAME, ANALYST_AGENT_NAME]
        assert [a["role"] for a in agents] == ["challenger", "analyst"]

    def test_the_reported_prompts_are_the_prompts_actually_executed(self) -> None:
        """Not a paraphrase of the defaults — the same constants ``service.py``
        falls back to. A panel showing a stale copy would be as misleading as
        the empty one it replaces."""
        challenger, analyst = builtin_chat_agents()

        assert challenger["system_prompt"] == CHALLENGER_INSTRUCTIONS
        assert analyst["system_prompt"] == ANALYST_INSTRUCTIONS

    def test_the_reported_models_are_the_models_the_founder_app_uses(self) -> None:
        """The drift guard: ``app.py`` resolves its models from this module, so
        the panel cannot report one model while requests run on another."""
        challenger, analyst = builtin_chat_agents()

        assert challenger["model"] == founder_app._CHAT_MODEL
        assert analyst["model"] == founder_app._ANALYSIS_MODEL

    def test_the_seed_script_stores_a_copy_of_the_shown_default(self) -> None:
        """Seeding (or clicking "store this default" in the panel) must write
        exactly what was displayed — otherwise the override silently changes
        behaviour, which is the trap issue #58 describes."""
        from scripts.seed_chat_agents import build_analyst_payload, build_payload

        challenger, analyst = builtin_chat_agents()
        assert build_payload() == challenger
        assert build_analyst_payload() == analyst


class TestModelResolution:
    def test_the_built_in_models_are_used_when_the_environment_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(CHAT_MODEL_ENV, raising=False)
        monkeypatch.delenv(ANALYSIS_MODEL_ENV, raising=False)

        assert chat_model() == DEFAULT_CHAT_MODEL
        assert analysis_model() == DEFAULT_ANALYSIS_MODEL

    def test_the_environment_overrides_the_built_in_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CHAT_MODEL_ENV, "vendor/chat-x")
        monkeypatch.setenv(ANALYSIS_MODEL_ENV, "vendor/analysis-x")

        assert chat_model() == "vendor/chat-x"
        assert analysis_model() == "vendor/analysis-x"
        assert [a["model"] for a in builtin_chat_agents()] == [
            "vendor/chat-x",
            "vendor/analysis-x",
        ]


class TestEffectiveModels:
    def test_both_models_in_use_are_reported_with_their_purpose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The model catalog is an admin-curated list nothing in the request
        path reads. These two are what actually reaches the runtime, so an empty
        catalog has to show them as inherited rather than as nothing."""
        monkeypatch.delenv(CHAT_MODEL_ENV, raising=False)
        monkeypatch.delenv(ANALYSIS_MODEL_ENV, raising=False)

        models = effective_models()

        assert [m["purpose"] for m in models] == ["chat", "analysis"]
        assert [m["model_id"] for m in models] == [DEFAULT_CHAT_MODEL, DEFAULT_ANALYSIS_MODEL]

    def test_a_value_names_where_it_came_from(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ "Which of these did somebody choose?" is the question an admin is
        actually asking, so ``source`` distinguishes an env override from the
        hardcoded fallback."""
        monkeypatch.setenv(CHAT_MODEL_ENV, "vendor/chat-x")
        monkeypatch.delenv(ANALYSIS_MODEL_ENV, raising=False)

        by_purpose = {m["purpose"]: m for m in effective_models()}

        assert by_purpose["chat"]["source"] == SOURCE_ENV
        assert by_purpose["chat"]["env_var"] == CHAT_MODEL_ENV
        assert by_purpose["analysis"]["source"] == SOURCE_BUILT_IN
        assert by_purpose["analysis"]["env_var"] == ANALYSIS_MODEL_ENV
