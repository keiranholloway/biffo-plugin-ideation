"""One normalisation for "JSON that may already be parsed".

Values reach this plugin from Core in two shapes, and which one arrives is not
a property of the *value* — it is a property of the transport that carried it.
An owner-data Text column comes back as JSON *text* over the HTTP transport and
as a `dict` from a JSON-typed one (or a fake in tests); a tool call's
``arguments`` field is a JSON string from one runtime and an already-decoded
object from another. Every reader therefore needs the same two-shape
normalisation, and it was written out by hand at each one::

    json.loads(value) if isinstance(value, str) else value

This module holds it once. The reason it is its own module rather than a
private function in `adapter.py` — where the first copy lived — is that the
second caller is `service.py`, which is deliberately transport-agnostic (no
HTTP, no AWS, no SDK) and must not import the adapter to reach a helper: that
would point the hexagon's dependency the wrong way round for the sake of one
ternary. A leaf module both layers may import costs nothing and keeps the
direction honest.

**Why this is worth a module at all.** `biffo-plugin-marketing` shipped this
exact ternary at seven call sites across six files; the issue that reported it
named two, and the five nobody had named would have survived a fix made as
filed, behind a closed issue, looking done (marketing #49/#111). The class is
`class:drift` — a helper adopted at some call sites and not others — and this
plugin was carrying the last known raw instance of it in the estate
(marketing #119). `tests/test_helper_adoption_sweep.py` is the guard that
stops the next one.
"""

from __future__ import annotations

import json
from typing import Any


def parse_json_text(value: Any) -> Any:
    """`value` decoded if it arrived as JSON text, and returned untouched if it
    did not.

    `None` passes straight through as `None` rather than becoming `{}`: a column
    that is genuinely NULL and a column holding ``"{}"`` are different facts,
    and every caller here distinguishes them (a missing report is not an empty
    report). A caller that wants a dict-or-empty should say so at its own site.

    Raises `json.JSONDecodeError` on text that is not JSON — the same failure
    the hand-written copies had, deliberately preserved: a malformed body from
    Core is a real fault and swallowing it here would turn a loud failure into a
    silently empty report.
    """
    return json.loads(value) if isinstance(value, str) else value
