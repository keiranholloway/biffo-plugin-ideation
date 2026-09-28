"""The manifest is the plugin's compliance surface (ADR-0017).

A user-facing plugin owns its own lifecycle and pins, at creation, the Core
capabilities it binds — a `core_capabilities` dependency map — plus a
`required_core_version` floor. These tests keep that declaration honest: every
seam the orchestration actually uses must be declared, and the CRUD-closed /
owner-scoped data model must stay closed.
"""

from __future__ import annotations

import json
from typing import Any

from ideation.manifest import MANIFEST_PATH

# The Core capabilities the orchestration binds (ADR-0017 §"Capabilities are the
# unit of compatibility"). Each maps to a CoreGateway seam the plugin depends on:
#   chat-turn                    -> run_chat_turn (the buffered challenger turn)
#   agent-run-request            -> request_analysis (kick the async analyst run)
#   agent-run-read               -> get_run (poll the analyst run's status)
#   run-output-tool              -> the submit_ideation_report inline tool schema
#   thread-messages-read         -> read the gathering conversation for the analyst
#   owner-scoped-tables          -> session/report reads+writes on closed tables
#   chat-agent-registry          -> registering the challenger/analyst at install
#   idea-submission-read         -> get_submitted_idea (the seed-idea prefill read)
# (No event:* — completion is materialised lazily on get_report, not via a
#  subscriber, so the plugin binds no event capability.)
REQUIRED_CAPABILITIES = frozenset(
    {
        "chat-turn",
        "agent-run-request",
        "agent-run-read",
        "run-output-tool",
        "thread-messages-read",
        "owner-scoped-tables",
        "chat-agent-registry",
        "idea-submission-read",
    }
)


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_is_valid_json() -> None:
    assert isinstance(_manifest(), dict)


def test_declares_a_core_version_floor() -> None:
    # A ">=" floor (the minimum Core that offers the capabilities), not a pin.
    floor = _manifest()["required_core_version"]
    assert floor.startswith(">=")


def test_dependency_map_covers_every_seam_bound() -> None:
    caps = _manifest()["core_capabilities"]
    # every capability the orchestration binds is declared...
    assert REQUIRED_CAPABILITIES <= set(caps)
    # ...and nothing is declared that isn't actually used (no phantom pins).
    assert set(caps) == REQUIRED_CAPABILITIES


def test_capability_pins_are_ranges_not_bare_versions() -> None:
    # >=/caret ranges opt in to compatible forward movement; a bare "1.0.0" would
    # pin to one release and defeat the lifecycle contract (ADR-0017).
    for capability, pin in _manifest()["core_capabilities"].items():
        assert pin[0] in "^>", f"{capability} pin {pin!r} must be a range"


# Founder-owned data (session/report rows) stays owner-scoped and CRUD-closed
# (ADR-0002 / ADR-0004 / ADR-0017 seam #5) — a founder's private data must never
# be reachable via tenant-wide generic CRUD. Admin-managed reference data (the
# model catalog) is the deliberate exception: it isn't owned by any one founder,
# so it uses Core's plugin-declared generic CRUD (ADR-0004), gated to the admin
# role instead of owner-scoped. See test_admin_managed_tables_require_the_admin_role.
_OWNER_SCOPED_TABLES = frozenset({"ideation_sessions", "ideation_reports"})


def test_owner_scoped_tables_stay_crud_closed() -> None:
    for table in _manifest()["tables"]:
        if table["name"] not in _OWNER_SCOPED_TABLES:
            continue
        perms = table["permissions"]
        assert all(
            not perms[action]["allowed"]
            for action in ("list", "read", "create", "update", "delete")
        ), f"{table['name']} must keep all CRUD permissions closed"


def test_every_owner_scoped_table_is_owner_scoped_on_a_real_column() -> None:
    # Each owner-scoped table opts into service-auth owner-scoped access
    # (ADR-0017 §5) on a column it actually declares, granted to this module's
    # own principal.
    for table in _manifest()["tables"]:
        if table["name"] not in _OWNER_SCOPED_TABLES:
            continue
        access = table["owner_scoped_service"]
        assert access["allowed_principals"] == ["system:ideation"]
        column_names = {c["name"] for c in table["columns"]}
        assert access["owner_column"] in column_names, (
            f"{table['name']} owner_column must be a declared column"
        )


def test_ideation_sessions_declares_the_challenger_agent_key_column() -> None:
    # The founder-facing agent picker (M10) pins this on the session at
    # creation — must be a real declared column, not just app-layer state.
    for table in _manifest()["tables"]:
        if table["name"] != "ideation_sessions":
            continue
        column_names = {c["name"] for c in table["columns"]}
        assert "challenger_agent_key" in column_names
        break
    else:
        raise AssertionError("ideation_sessions table not found in manifest")


def test_admin_managed_tables_require_the_admin_role() -> None:
    # The model catalog is deliberately NOT owner-scoped (it isn't founder-owned
    # data) — it uses tenant-wide generic CRUD, gated to the admin role on every
    # operation, so it never accidentally opens to any authenticated caller.
    for table in _manifest()["tables"]:
        if table["name"] in _OWNER_SCOPED_TABLES:
            continue
        assert "owner_scoped_service" not in table, (
            f"{table['name']} is admin-managed, not owner-scoped — should not "
            "declare owner_scoped_service"
        )
        perms = table["permissions"]
        for action in ("list", "read", "create", "update", "delete"):
            assert perms[action]["allowed"] is True, (
                f"{table['name']}.{action} should be open (admin-gated), not closed"
            )
            assert perms[action]["required_role"] == ["admin"], (
                f"{table['name']}.{action} must require the admin role"
            )


def test_admin_managed_tables_have_matching_api_routes() -> None:
    # Every admin-managed table's generic CRUD is actually reachable — a
    # permissions block with no api_routes entry would be exposed nowhere.
    admin_tables = {
        t["name"] for t in _manifest()["tables"] if t["name"] not in _OWNER_SCOPED_TABLES
    }
    routed_tables = {r["table"] for r in _manifest()["api_routes"]}
    assert admin_tables <= routed_tables


def test_the_model_catalog_declares_every_route_the_admin_ui_calls() -> None:
    # The admin UI calls these five directly at /api/v1/plugins/ideation/... —
    # they are served by Core and forwarded by the plugin host
    # (biffo-template#684), NOT proxied by admin_app any more. If a declaration
    # is dropped here, the host stops recognising the path and the request falls
    # through to the founder-gated plugin app instead: a 404 (or a 403 for an
    # admin who is not also a founder), not an obvious missing route.
    declared = {(r["method"], r["path"]) for r in _manifest()["api_routes"]}
    assert declared >= {
        ("GET", "/model-catalog"),
        ("POST", "/model-catalog"),
        ("GET", "/model-catalog/{id}"),
        ("PUT", "/model-catalog/{id}"),
        ("DELETE", "/model-catalog/{id}"),
    }


def test_the_core_floor_covers_declared_route_forwarding() -> None:
    # Forwarding manifest-declared api_routes to Core landed in core 0.136.0
    # (biffo-template#684). The admin UI now depends on it, so a Core below that
    # would mount this plugin and silently serve no model catalog at all.
    floor = _manifest()["required_core_version"].removeprefix(">=")
    major, minor, patch = (int(part) for part in floor.split("."))
    assert (major, minor, patch) >= (0, 136, 0), (
        f"core floor {floor} predates declared-route forwarding (0.136.0)"
    )


def test_declares_an_admin_gated_user_ingress_pointing_at_the_asgi_app() -> None:
    # ADR-0021: the shared plugin host mounts this app. user_ingress references the
    # ASGI app as "<module>:<attr>", gated to the admin group (owner decision B on
    # biffo-platform-app#70 — "founder" is a biffo-platform-only concept; other
    # platforms use admin only). No handler/path — the host owns the Lambda
    # entrypoint and the mount prefix.
    ingress = _manifest()["user_ingress"]
    assert ingress["required_group"] == "admin"
    assert ingress["app"] == "ideation.app:app"
    assert "handler" not in ingress
    assert "path" not in ingress


def test_declares_an_admin_gated_user_frontend() -> None:
    frontend = _manifest()["user_frontend"]
    assert frontend["required_group"] == "admin"
    assert frontend["dir"]  # the built static export directory


def test_opts_into_live_chat_agent_registry() -> None:
    # The manifest declares chat_agents_dynamic: true to use Core's live,
    # DB-backed chat-agent registry instead of the frozen-at-deploy static one.
    assert _manifest()["chat_agents_dynamic"] is True


def test_declares_no_static_chat_agents_beside_the_dynamic_flag() -> None:
    # Core's register_plugin_chat_agents() skips a manifest outright when
    # chat_agents_dynamic is set, so a chat_agents block here is never read.
    # It carried a full second copy of CHALLENGER_INSTRUCTIONS: two prompts,
    # one live and one unreachable, with nothing keeping them equal. They were
    # still byte-identical when the block was removed, so this guards against a
    # latent drift rather than a realised one — but the copy that would have
    # drifted is the one no test could have caught, because nothing executes it.
    assert "chat_agents" not in _manifest()


# ---------------------------------------------------------------------------
# The required-group literal has no second home (issues #163, #171).
#
# Three fixes of the same defect landed before anyone consolidated it: the
# manifest moved to "admin" (#162), app.py's own gate kept "founder" and 403'd
# every admitted caller (#163/#170), and the chat-agent seed payload kept
# "founder" at a *different* enforcement point and 403'd them one step later
# (#171). Each fix corrected a copy. These pin the consolidation instead.
# ---------------------------------------------------------------------------


def test_manifest_required_group_reads_each_surface_from_the_manifest() -> None:
    from ideation.manifest import manifest_required_group

    manifest = _manifest()
    for surface in ("user_ingress", "admin_ingress"):
        assert manifest_required_group(surface) == manifest[surface]["required_group"]


def test_manifest_required_group_fails_closed_on_a_surface_that_declares_none() -> None:
    """A typo'd or group-less surface must raise, not return None — a gate built
    from None admits or refuses the wrong audience silently, which is the whole
    failure mode this helper exists to end."""
    import pytest

    from ideation.manifest import manifest_required_group

    with pytest.raises(KeyError):
        manifest_required_group("no_such_ingress")


# ---------------------------------------------------------------------------
# Path resolution under the shared plugin host's deploy layout (issue #173).
#
# The old ``_resolve_manifest_path()`` walked up from this module looking for
# ``biffo.plugin.json`` alongside its own source — correct in this repo
# checkout, but the shared host's deploy-app.yml copies this plugin's ``src/``
# straight to the Lambda task root while placing the manifest at
# ``services/ideation/biffo.plugin.json``, a *sibling* of the flattened
# ``src/``, not an ancestor of it. No walk-up from the module reaches that.
# Because ``app.py`` reads the manifest at *import* time
# (``manifest_required_group("user_ingress")`` at module scope), a resolution
# miss didn't just fail one request — it crashed the whole Lambda at cold
# start. Confirmed live on biffo-platform's dev environment 2026-09-23.
# ---------------------------------------------------------------------------


def test_resolves_under_the_deployed_layout_when_plugins_root_is_set(tmp_path) -> None:
    """The fix: BIFFO_PLUGINS_ROOT (already set on the Lambda for
    discover_plugins()'s own manifest scan, per admin_app.py's
    _resolve_static_dir) anchors the manifest at
    services/ideation/biffo.plugin.json directly, independent of __file__'s
    location -- so the flattened-src deploy layout resolves correctly."""
    from ideation.manifest import _resolve_manifest_path

    services_root = tmp_path / "var" / "task" / "services"
    manifest_file = services_root / "ideation" / "biffo.plugin.json"
    manifest_file.parent.mkdir(parents=True)
    manifest_file.write_text("{}")

    result = _resolve_manifest_path(str(services_root))

    assert result == manifest_file
    assert result.is_file()


def test_falls_back_to_the_repo_walkup_when_plugins_root_is_unset() -> None:
    """Local dev / this module's own tests: no BIFFO_PLUGINS_ROOT, so
    resolution walks up from this module and finds the real repo-root
    manifest -- unchanged from before this fix."""
    from ideation.manifest import MANIFEST_PATH, _resolve_manifest_path

    assert _resolve_manifest_path(None) == MANIFEST_PATH
    assert MANIFEST_PATH.is_file()


def test_falls_back_when_plugins_root_is_empty_string() -> None:
    from ideation.manifest import MANIFEST_PATH, _resolve_manifest_path

    assert _resolve_manifest_path("") == MANIFEST_PATH


def test_old_walkup_alone_cannot_find_the_manifest_under_the_deployed_layout(
    tmp_path, monkeypatch
) -> None:
    """Fail-first: reproduces the exact crash this issue reports. Simulates the
    deployed layout -- this module's own __file__ living under a flattened
    task root, with no biffo.plugin.json anywhere in its parent chain (it's a
    sibling under services/, per deploy-app.yml) -- and shows the walk-up
    genuinely finds nothing there. Without the BIFFO_PLUGINS_ROOT branch this
    fix adds, that nonexistent last-resort path is exactly what MANIFEST_PATH
    resolved to in production, and manifest_required_group()'s .read_text()
    raised FileNotFoundError at import time, crashing the whole Lambda."""
    import ideation.manifest as manifest_module

    task_root = tmp_path / "var" / "task"
    fake_module_file = task_root / "ideation" / "manifest.py"
    fake_module_file.parent.mkdir(parents=True)
    fake_module_file.write_text("")

    monkeypatch.setattr(manifest_module, "__file__", str(fake_module_file))

    result = manifest_module._resolve_manifest_path(None)

    assert not result.is_file(), (
        "the walk-up alone found a manifest under the flattened deploy layout "
        "-- it shouldn't, since the real manifest sits at services/ideation/, "
        "a sibling of the flattened src/, not an ancestor of it"
    )


def test_no_module_hardcodes_a_group_literal_in_its_gate() -> None:
    """The guard, not just the fix: every ``require_group(...)`` in the package
    must take its argument from the manifest helper.

    A literal here is exactly what #163 and #171 were — a hand-maintained copy
    of a manifest field, correct on the day it was written and silently wrong
    the day the manifest moved. ``admin_app.py``'s ``require_group("admin")``
    was the copy still standing when #171 was fixed; it agreed with the manifest
    at the time, which is precisely how the previous two survived review.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parent.parent / "src" / "ideation"
    offenders: list[str] = []

    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "require_group":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant):
                    offenders.append(f"{path.name}:{node.lineno} require_group({arg.value!r})")

    assert offenders == [], (
        "these gates hardcode a group instead of calling "
        f"manifest_required_group(<surface>): {offenders}"
    )
