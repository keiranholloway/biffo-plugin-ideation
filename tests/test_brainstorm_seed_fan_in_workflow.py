"""The workflow definition Brain-Storming cannot run without.

Without it a session never leaves `researching`: the six research agents run,
bill, and nothing reconciles them. That failure is silent, so the contents of
this definition are asserted rather than trusted.
"""

from __future__ import annotations

from ideation.brainstorm_definitions import (
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
)
from scripts import seed_brainstorm_fan_in_workflow as _seed

WORKFLOW_NAME = _seed.WORKFLOW_NAME
definition = _seed.definition


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
    """The name is the idempotency key the seeder matches on — changing it would
    seed a duplicate rather than replace."""
    payload = definition()

    assert payload["enabled"] is True
    assert payload["name"] == WORKFLOW_NAME


def test_it_posts_to_the_path_core_actually_mounts():
    """Every other test here validates the *payload* and none validated the
    *endpoint*, so the script shipped posting to a path that has never existed
    and the suite stayed green (#119).

    Core mounts workflow-definition CRUD at `/api/v1/orchestration/workflows`:
    the router declares `prefix="/orchestration/workflows"` and is included
    with `prefix="/api/v1"`. `/api/v1/admin/orchestration` is a *different*
    router that exposes only `/test` (the dry-run), so the `admin/` variant
    404s exactly like a route that was never defined — which is why nothing
    surfaced it: the seeder reported `Could not list workflows: 404 Not Found`
    and that reads as a permissions or environment problem, not a wrong URL.

    The sibling plugin measured the same constant against deployed dev on
    2026-08-11 with a valid admin token: `/api/v1/orchestration/workflows`
    -> 200, `/api/v1/admin/...` -> 404, identical to a known-bad control path.

    This pins the string; it cannot prove Core still mounts it there. A 404
    from this script means check the deployed `openapi.json` before assuming
    the token or the environment is at fault.
    """
    assert _seed._DEFINITIONS_PATH == "/api/v1/orchestration/workflows"
    assert "/admin/" not in _seed._DEFINITIONS_PATH


def _run_main(monkeypatch, capsys, fail_on: str, argv: list[str] | None = None):
    import urllib.error

    monkeypatch.setenv("CORE_API_URL", "http://core")
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "t")
    monkeypatch.setattr("sys.argv", ["seed", *(argv or [])])

    def fake_request(method, url, token, body=None):
        if method == fail_on:
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)  # type: ignore[arg-type]
        return [{"id": "w1", "name": WORKFLOW_NAME}] if method == "GET" else {"id": "n"}

    monkeypatch.setattr(_seed, "_request", fake_request)
    rc = _seed.main()
    return rc, capsys.readouterr().err


def test_main_reports_failure_to_list_workflows(monkeypatch, capsys):
    rc, err = _run_main(monkeypatch, capsys, "GET")
    assert rc == 1 and "Could not list workflows" in err


def test_main_reports_failure_to_replace_workflow(monkeypatch, capsys):
    rc, err = _run_main(monkeypatch, capsys, "PUT", ["--replace"])
    assert rc == 1 and "Failed: 500" in err
