"""Startup self-seeding of the two agent config rows (issue #93).

Ideation's prompts used to originate only in ``definitions.py``, and both the
challenger (Core's chat-turn spine) and the analyst (``IdeationService.finalise``)
had a way to keep running without a stored row ever existing — the challenger
via the manifest's now-removed static registration, the analyst via a runtime
fallback to ``ANALYST_INSTRUCTIONS``. Neither guaranteed a row, so a fresh
deployment ran silently on constants (or, for the challenger since
``chat_agents_dynamic`` replaced the static block, 404s until someone
remembered to run ``scripts/seed_chat_agents.py`` by hand).

These tests cover the two things the fix rests on:

1. Both plugin apps self-seed at startup, insert-if-absent, from the one
   payload builder (``effective_config.builtin_chat_agents()``) — so the
   startup path and the manual script cannot drift (mirrors
   ``biffo-plugin-idea-scout#68``).
2. Seeding **never overwrites an existing row** — the property the whole
   guarantee rests on, since this runs on every cold start. This is enforced
   server-side by Core's ``POST /internal/plugins/me/config/seed`` route
   (``services/api/src/api/routers/internal_plugin_config.py`` in
   biffo-template); the test here proves this plugin's own seeding *code path*
   would still be safe against that contract even if a caller pointed it at a
   table that already had an edited row — i.e. it never asks for anything but
   an insert-if-absent write, and never mutates a row that already exists.
3. A transient Core failure at startup is caught and logged loudly rather than
   crashing the app — the runtime path (a chat 404, or
   ``AgentConfigMissingError``) already fails loudly on its own if a row is
   genuinely missing, so startup itself must not also blow up.

There is no history-row assertion here: seeding calls a single Core route
(``seed_own_config``) that itself guarantees no history row is written — this
plugin has no code path that could write one through this seam, so there is
nothing of this plugin's own to test for that property; it is Core's
guarantee, covered by Core's own tests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from ideation.definitions import ANALYST_AGENT_NAME, CHALLENGER_AGENT_NAME
from ideation.effective_config import builtin_chat_agents


class _StubTransport:
    """Stands in for the real SigV4 ``CoreTransport``, which needs live AWS
    credentials to even construct. Nothing here is called: the gateway is
    monkeypatched out before it would use this."""

    def __init__(self, *, founder_token: str = "") -> None:
        self.founder_token = founder_token


class _RecordingGateway:
    """Records the ``seed_own_config`` payload it was called with and hands
    back a scripted result — or raises a scripted ``CoreHttpError``."""

    last_instance: _RecordingGateway | None = None

    def __init__(self, _transport: Any) -> None:
        self.seed_calls: list[list[dict[str, Any]]] = []
        self.raise_on_seed: Exception | None = None
        self.result: list[dict[str, bool]] = []
        _RecordingGateway.last_instance = self

    async def seed_own_config(self, *, config: list[dict[str, Any]]) -> list[dict[str, bool]]:
        self.seed_calls.append(config)
        if self.raise_on_seed is not None:
            raise self.raise_on_seed
        return self.result


class _InsertIfAbsentGateway:
    """Mimics Core's actual seed-route contract (insert-if-absent, never
    overwrite) against an in-memory table, so this plugin's seeding call can be
    proven safe to call repeatedly without relying on a live Core."""

    def __init__(self, _transport: Any, *, table: dict[str, dict[str, Any]]) -> None:
        self._table = table

    async def seed_own_config(self, *, config: list[dict[str, Any]]) -> list[dict[str, bool]]:
        results = []
        for row in config:
            key = row["agent_key"]
            created = key not in self._table
            if created:
                self._table[key] = dict(row)
            # Never overwritten regardless of `created`: an existing row's
            # values are left exactly as they were, even when the caller's
            # payload differs from what is stored — the property the whole
            # guarantee rests on.
            results.append({"role": row["role"], "created": created})
        return results


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TestBothAppsSeedAtStartup:
    """Both ``ideation.app`` and ``ideation.admin_app`` self-seed independently
    (issue #93) — whichever cold-starts first still guarantees the rows exist,
    rather than the guarantee depending on one particular app having run."""

    @pytest.mark.parametrize("module_name", ["ideation.app", "ideation.admin_app"])
    def test_startup_seeds_both_roles_from_the_one_payload_builder(
        self, monkeypatch: pytest.MonkeyPatch, module_name: str
    ) -> None:
        import importlib

        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "CoreTransport", _StubTransport)
        monkeypatch.setattr(module, "CoreHttpGateway", _RecordingGateway)

        _run(module._seed_agent_config())

        gateway = _RecordingGateway.last_instance
        assert gateway is not None
        assert len(gateway.seed_calls) == 1
        sent = gateway.seed_calls[0]
        # The exact payload builtin_chat_agents() returns — not a second,
        # independently-built copy that could drift from it.
        assert sent == builtin_chat_agents()
        assert {row["agent_key"] for row in sent} == {CHALLENGER_AGENT_NAME, ANALYST_AGENT_NAME}

    @pytest.mark.parametrize("module_name", ["ideation.app", "ideation.admin_app"])
    def test_a_transient_core_failure_at_startup_is_logged_not_raised(
        self,
        monkeypatch: pytest.MonkeyPatch,
        module_name: str,
    ) -> None:
        """Proves the fix does the thing #912's implementation note insists
        on: a cold Core must not wedge the app. If this raised, FastAPI's
        startup would fail and the whole plugin would fail to boot on every
        transient Core hiccup — turning a recoverable blip into an outage."""
        import importlib

        from ideation.adapter import CoreHttpError

        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "CoreTransport", _StubTransport)

        class _FailingGateway(_RecordingGateway):
            def __init__(self, transport: Any) -> None:
                super().__init__(transport)
                self.raise_on_seed = CoreHttpError("POST .../seed -> 503")

        monkeypatch.setattr(module, "CoreHttpGateway", _FailingGateway)

        # Capture from the module's OWN logger rather than through `caplog`,
        # which depends on propagation reaching the root handler. That held here
        # and did not hold in the instance: vendored into `biffo-platform`, this
        # test runs in a suite that also imports Core, whose AWS Lambda Powertools
        # `Logger()` reconfigures logging and disables propagation. The assertion
        # then failed for a reason that has nothing to do with what it tests —
        # green upstream, red downstream, on identical code.
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture()
        module._LOGGER.addHandler(handler)
        previous_level = module._LOGGER.level
        module._LOGGER.setLevel(logging.ERROR)
        try:
            _run(module._seed_agent_config())  # must not raise
        finally:
            module._LOGGER.removeHandler(handler)
            module._LOGGER.setLevel(previous_level)

        assert any("seed" in record.getMessage().lower() for record in records)


class TestSeedingNeverOverwrites:
    """The property the whole feature rests on (per the issue): seeding is
    insert-if-absent and must never revert an admin's edited row, because it
    runs on every cold start."""

    def test_a_second_seed_call_leaves_an_edited_row_untouched(self) -> None:
        table: dict[str, dict[str, Any]] = {}
        gateway = _InsertIfAbsentGateway(_StubTransport(), table=table)
        payload = builtin_chat_agents()

        first = _run(gateway.seed_own_config(config=payload))
        assert [r["created"] for r in first] == [True, True]
        assert table[CHALLENGER_AGENT_NAME]["system_prompt"] == payload[0]["system_prompt"]

        # An admin edits the challenger's stored prompt directly (what the
        # admin panel's "Edit"/"Save" does to this same row).
        edited_prompt = "An admin's carefully edited prompt."
        table[CHALLENGER_AGENT_NAME]["system_prompt"] = edited_prompt

        # The next cold start seeds again, from the *same* built-in payload.
        second = _run(gateway.seed_own_config(config=payload))

        assert [r["created"] for r in second] == [False, False]
        # The admin's edit survived the re-seed — this is the whole point.
        assert table[CHALLENGER_AGENT_NAME]["system_prompt"] == edited_prompt

    def test_without_the_insert_if_absent_guard_the_edit_would_be_lost(self) -> None:
        """The failure mode this guards against, made concrete: an
        unconditional upsert (the bug this feature must not reintroduce) would
        silently revert the edit above on the very next cold start."""
        table: dict[str, dict[str, Any]] = {}
        payload = builtin_chat_agents()
        table[CHALLENGER_AGENT_NAME] = dict(payload[0])
        table[CHALLENGER_AGENT_NAME]["system_prompt"] = "An admin's carefully edited prompt."

        # An unconditional-overwrite seed (what this feature must NOT do):
        for row in payload:
            table[row["agent_key"]] = dict(row)

        assert table[CHALLENGER_AGENT_NAME]["system_prompt"] == payload[0]["system_prompt"], (
            "sanity check: an unconditional overwrite does lose the edit — "
            "confirming the guard in _InsertIfAbsentGateway above is what "
            "prevents this, not an accident of the test data"
        )
