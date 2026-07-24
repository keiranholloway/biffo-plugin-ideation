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


def test_all_tables_stay_crud_closed() -> None:
    # Data lives in Core, served only over the owner-scoped service seam — never
    # tenant-scoped generic CRUD (ADR-0002 / ADR-0004 / ADR-0017 seam #5).
    for table in _manifest()["tables"]:
        perms = table["permissions"]
        assert all(
            not perms[action]["allowed"]
            for action in ("list", "read", "create", "update", "delete")
        ), f"{table['name']} must keep all CRUD permissions closed"


def test_every_table_is_owner_scoped_on_a_real_column() -> None:
    # Each table opts into service-auth owner-scoped access (ADR-0017 §5) on a
    # column it actually declares, granted to this module's own principal.
    for table in _manifest()["tables"]:
        access = table["owner_scoped_service"]
        assert access["allowed_principals"] == ["system:ideation"]
        column_names = {c["name"] for c in table["columns"]}
        assert access["owner_column"] in column_names, (
            f"{table['name']} owner_column must be a declared column"
        )


def test_declares_a_founder_gated_user_ingress_pointing_at_the_asgi_app() -> None:
    # ADR-0021: the shared plugin host mounts this app. user_ingress references the
    # ASGI app as "<module>:<attr>", gated to the founder group. No handler/path —
    # the host owns the Lambda entrypoint and the mount prefix.
    ingress = _manifest()["user_ingress"]
    assert ingress["required_group"] == "founder"
    assert ingress["app"] == "ideation.app:app"
    assert "handler" not in ingress
    assert "path" not in ingress


def test_declares_a_founder_gated_user_frontend() -> None:
    frontend = _manifest()["user_frontend"]
    assert frontend["required_group"] == "founder"
    assert frontend["dir"]  # the built static export directory
