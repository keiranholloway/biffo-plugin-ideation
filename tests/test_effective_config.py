"""The effective configuration the engine actually runs on (issues #58, #67).

The admin panel used to list the chat-agent table and report "No agents defined
yet" on an empty one — true about the table, false about the system (#58). Its
replacement then reported the *built-in* models as in use however the table
looked, which was false the other way (#67): the challenger's model comes only
from its stored row, and the analyst's does too whenever a row exists.

These tests hold the views of those defaults together — what the seed script
would store, what ``ideation.app`` falls back to for the analyst, and what the
admin panel is told — and pin that the panel's answer is resolved against the
stored rows rather than asserted from constants.
"""

from __future__ import annotations

from typing import Any

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
    SOURCE_STORED,
    SOURCE_UNCONFIGURED,
    SOURCE_UNKNOWN,
    analysis_model,
    builtin_chat_agents,
    chat_model,
    effective_models,
)


def _row(**overrides: Any) -> dict[str, Any]:
    """A stored chat-agent row as Core's admin list route returns one."""
    return {
        "agent_key": CHALLENGER_AGENT_NAME,
        "agent_name": CHALLENGER_AGENT_NAME,
        "role": "challenger",
        "system_prompt": "stored prompt",
        "model": "vendor/stored-chat",
        "required_group": "founder",
        "active": True,
        **overrides,
    }


def _by_purpose(stored: Any) -> dict[str, dict[str, Any]]:
    return {m["purpose"]: m for m in effective_models(stored)}


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

    def test_the_analyst_default_is_the_one_the_founder_app_falls_back_to(self) -> None:
        """The drift guard for the one model that genuinely has a fallback:
        ``app.py`` resolves the analyst's from this module, so the seeded
        default cannot differ from what ``finalise`` actually falls back to.

        There is deliberately no challenger equivalent. ``app.py`` used to hold
        a chat model and hand it to the service, which handed it to the adapter,
        which dropped it — so this guard asserted agreement between two values
        neither of which reached a request (issue #68). The challenger's real
        agreement is between this module and the seed script, below."""
        _challenger, analyst = builtin_chat_agents()

        assert analyst["model"] == founder_app._ANALYSIS_MODEL
        assert not hasattr(founder_app, "_CHAT_MODEL")

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

    def test_the_analyst_default_searches_the_web_on_a_slug_openrouter_serves(self) -> None:
        # Two separate regressions, both silent, both only visible at runtime:
        #
        # 1. The slug was "anthropic/claude-opus-4-8" — hyphenated, and absent
        #    from every one of the 367 models OpenRouter lists. The challenger's
        #    "claude-sonnet-4" IS served, so chat worked and only the report was
        #    broken, which read as flakiness rather than a bad model id.
        # 2. Research depended on the web_search registry tool, which a
        #    deployment without a Brave credential never offers — and dev's is the
        #    empty string. Without :online the analyst invents competitors.
        assert DEFAULT_ANALYSIS_MODEL.endswith(":online")
        base = DEFAULT_ANALYSIS_MODEL.removesuffix(":online")
        assert base == "anthropic/claude-opus-4.8"
        assert "-4-8" not in base, "the OpenRouter slug is dotted, not hyphenated"

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
    def test_both_purposes_are_reported_in_a_stable_order(self) -> None:
        """The model catalog is the admin-curated list a model is chosen
        *from*; nothing in the request path reads it. These two are what a
        request runs on, so an empty catalog must still show them."""
        models = effective_models([])

        assert [m["purpose"] for m in models] == ["chat", "analysis"]

    def test_the_stored_challenger_row_is_what_the_chat_model_is_reported_as(self) -> None:
        """The bug in #67: the panel reported the built-in constant while the
        stored row was the only thing Core resolves the challenger's model
        from. Reporting must follow the row."""
        by_purpose = _by_purpose([_row(model="vendor/stored-chat")])

        assert by_purpose["chat"]["model_id"] == "vendor/stored-chat"
        assert by_purpose["chat"]["source"] == SOURCE_STORED

    def test_a_stored_challenger_row_wins_over_the_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``IDEATION_CHAT_MODEL`` is never sent to Core (adapter.run_chat_turn
        sends no model at all), so it cannot change what a chat turn runs on.
        Reporting it as the model in use is the precise failure #67 names: the
        panel would change while the runtime did not."""
        monkeypatch.setenv(CHAT_MODEL_ENV, "vendor/env-chat")

        chat = _by_purpose([_row(model="vendor/stored-chat")])["chat"]

        assert chat["model_id"] == "vendor/stored-chat"
        assert chat["source"] == SOURCE_STORED
        # The env var still decides what a *seed* would write — and the payload
        # says which of the two that is, so the panel can show both.
        assert chat["builtin_model_id"] == "vendor/env-chat"
        assert chat["env_var_is_runtime_fallback"] is False

    def test_no_stored_challenger_row_is_unconfigured_not_a_built_in_default(self) -> None:
        """There is no built-in fallback for chat. With chat_agents_dynamic on,
        a missing row means Core has nothing to resolve and every turn 404s —
        so "running on the built-in default" would be the opposite of true, and
        would hide a broken deployment behind a plausible model id."""
        chat = _by_purpose([_row(agent_key="some-other-challenger")])["chat"]

        assert chat["source"] == SOURCE_UNCONFIGURED
        assert chat["model_id"] is None

    def test_the_stored_active_analyst_row_is_what_the_analysis_model_is_reported_as(
        self,
    ) -> None:
        """``finalise`` reads this row live and uses ``analyst_config["model"]``,
        so a panel reporting the built-in while a row exists describes a run
        that never happens."""
        analysis = _by_purpose(
            [_row(agent_key=ANALYST_AGENT_NAME, role="analyst", model="vendor/stored-analysis")]
        )["analysis"]

        assert analysis["model_id"] == "vendor/stored-analysis"
        assert analysis["source"] == SOURCE_STORED

    def test_an_inactive_analyst_row_does_not_count_as_configured(self) -> None:
        """``get_own_config`` resolves the *active* row for the role; an
        inactive one must not be reported as what runs."""
        analysis = _by_purpose(
            [_row(agent_key=ANALYST_AGENT_NAME, role="analyst", model="vendor/x", active=False)]
        )["analysis"]

        assert analysis["source"] == SOURCE_BUILT_IN
        assert analysis["model_id"] == DEFAULT_ANALYSIS_MODEL

    def test_the_analysis_fallback_is_real_and_names_where_it_came_from(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike chat, the analyst genuinely falls back — so with no stored
        row the built-in/env value IS what runs, and ``source`` says which."""
        monkeypatch.delenv(ANALYSIS_MODEL_ENV, raising=False)
        assert _by_purpose([])["analysis"] == {
            **_by_purpose([])["analysis"],
            "source": SOURCE_BUILT_IN,
            "model_id": DEFAULT_ANALYSIS_MODEL,
            "env_var": ANALYSIS_MODEL_ENV,
            "env_var_is_runtime_fallback": True,
        }

        monkeypatch.setenv(ANALYSIS_MODEL_ENV, "vendor/analysis-x")
        analysis = _by_purpose([])["analysis"]
        assert analysis["source"] == SOURCE_ENV
        assert analysis["model_id"] == "vendor/analysis-x"

    def test_an_unreadable_table_is_unknown_not_unconfigured(self) -> None:
        """``None`` means "we could not look", which is a different claim from
        "nothing is stored". Collapsing them would tell an admin their chat
        agent was missing every time Core cold-started."""
        by_purpose = _by_purpose(None)

        assert [m["source"] for m in by_purpose.values()] == [SOURCE_UNKNOWN, SOURCE_UNKNOWN]
        assert all(m["model_id"] is None for m in by_purpose.values())

    def test_every_entry_explains_itself(self) -> None:
        """The wording lives here, next to the resolution rule, so the panel
        cannot describe a source the resolver does not implement."""
        for stored in ([], None, [_row()], [_row(agent_key=ANALYST_AGENT_NAME, role="analyst")]):
            for entry in effective_models(stored):
                assert entry["detail"].strip()
                assert entry["builtin_model_id"]

    def test_the_stored_rows_must_be_passed_in(self) -> None:
        """No default argument: the old signature let a caller answer "what is
        in use?" without looking at what is stored, which is how the built-in
        constant came to be reported as the live model (#67)."""
        with pytest.raises(TypeError):
            effective_models()  # type: ignore[call-arg]
