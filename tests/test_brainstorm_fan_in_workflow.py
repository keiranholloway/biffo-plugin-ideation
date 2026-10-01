"""The workflow definition Brain-Storming cannot run without.

Without it a session never leaves `researching`: the six research agents run,
bill, and nothing reconciles them. That failure is silent, so the contents of
this definition are asserted rather than trusted.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from ideation.brainstorm_definitions import (
    FAN_IN_DEFINITION_KEY,
    OPPORTUNITIES_TOOL_NAME,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
    SYNTHESIS_TIMEOUT_SECONDS,
    WORKFLOW_NAME,
    brainstorm_workflow_definitions,
    opportunities_tool_schema,
)
from ideation.brainstorm_definitions import (
    brainstorm_fan_in_definition as definition,
)


def test_it_waits_for_all_six_research_agents():
    names = definition()["action_config"]["expect_agents"].split(",")

    assert len(names) == 6
    assert len(set(names)) == 6


def test_it_waits_for_exactly_the_agents_the_plugin_requests():
    """The names in expect_agents and the names start_run actually fires must be
    the same set. A drift here is a run that hangs forever."""
    config = definition()["action_config"]

    assert config["expect_agents"].split(",") == list(RESEARCH_AGENT_NAMES)


def test_it_fires_the_synthesis_agent_the_plugin_looks_for():
    """The plugin discovers the engine's run by agent name — these must match."""
    config = definition()["action_config"]

    assert config["agent_name"] == SYNTHESIS_AGENT_NAME


def test_it_does_not_carry_the_synthesis_prompt_or_model():
    """The prompt and model are no longer frozen into the workflow — Core resolves
    them from the plugin's seeded config, so admin edits take effect immediately."""
    config = definition()["action_config"]

    assert "instructions" not in config
    assert "model" not in config


def test_it_offers_synthesis_the_output_tool_the_plugin_parses():
    """Core builds the synthesis run's definition from this action_config, so the
    output tool must be here. Without it the model answers in prose,
    extract_opportunities finds no tool call, and every session ends `failed`
    ("returned nothing usable") after all six research agents have run and billed."""
    config = definition()["action_config"]

    assert config["output_tools"] == [opportunities_tool_schema()]
    assert config["output_tools"][0]["function"]["name"] == OPPORTUNITIES_TOOL_NAME


def test_it_bounds_the_synthesis_run_time():
    config = definition()["action_config"]

    assert config["timeout_seconds"] == SYNTHESIS_TIMEOUT_SECONDS > 0


def test_it_carries_max_turns():
    """Max turns is still required to bound the synthesis agent's cost."""
    config = definition()["action_config"]

    assert "max_turns" in config


def test_it_triggers_on_agent_completions():
    payload = definition()

    assert payload["trigger_source"] == "biffo.core"
    assert payload["trigger_detail_type"] == "agent.run.completed"
    assert payload["action_type"] == "agent_fan_in"


def test_it_is_enabled_and_named_stably():
    """The definition_key is the upsert key Core matches on — changing it would
    seed a duplicate rather than replace."""
    payload = definition()

    assert payload["enabled"] is True
    assert payload["name"] == WORKFLOW_NAME
    assert payload["definition_key"] == FAN_IN_DEFINITION_KEY == "ideation-brainstorm-fan-in"


class _StubTransport:
    def __init__(self, *, founder_token: str = "") -> None:
        pass


@pytest.mark.parametrize("module_name", ["ideation.app", "ideation.admin_app"])
def test_startup_posts_fan_in_definition_and_is_idempotent(monkeypatch, module_name):
    """Startup declares the definition to Core's workflow seed route with the
    stable key, and a second startup posts the identical payload."""
    from ideation.adapter import CoreHttpGateway

    module = importlib.import_module(module_name)
    posts: list[tuple[str, str, object]] = []

    class _Transport(_StubTransport):
        async def request(self, method, path, **kw):
            posts.append((method, path, kw.get("json")))
            return [{"definition_key": FAN_IN_DEFINITION_KEY, "created": len(posts) == 1}]

    monkeypatch.setattr(module, "CoreTransport", _Transport)
    monkeypatch.setattr(module, "CoreHttpGateway", CoreHttpGateway)

    asyncio.run(module._seed_workflows())
    asyncio.run(module._seed_workflows())

    assert len(posts) == 2
    method, path, body = posts[0]
    assert (method, path) == ("POST", "/api/v1/internal/plugins/me/workflows/seed")
    assert body == brainstorm_workflow_definitions()
    assert isinstance(body, list)
    assert body[0]["definition_key"] == FAN_IN_DEFINITION_KEY
    assert posts[1] == posts[0]


@pytest.mark.parametrize("module_name", ["ideation.app", "ideation.admin_app"])
def test_startup_workflow_failure_is_logged_not_raised(monkeypatch, module_name):
    from ideation.adapter import CoreHttpError

    module = importlib.import_module(module_name)

    class _Failing:
        def __init__(self, _t):
            pass

        async def seed_own_workflows(self, *, definitions):
            raise CoreHttpError("boom")

    monkeypatch.setattr(module, "CoreTransport", _StubTransport)
    monkeypatch.setattr(module, "CoreHttpGateway", _Failing)
    asyncio.run(module._seed_workflows())  # must not raise
