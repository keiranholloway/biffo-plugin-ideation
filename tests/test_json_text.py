"""`json_text.parse_json_text` — the one normalisation for "JSON that may
already be parsed".

These pin the contract the two call sites depend on, and in particular the two
decisions that are easy to "tidy" into a defect later: `None` stays `None`
rather than becoming `{}`, and malformed text still raises.
"""

from __future__ import annotations

import json

import pytest

from ideation.json_text import parse_json_text


def test_json_text_is_decoded() -> None:
    assert parse_json_text('{"verdict": "proceed"}') == {"verdict": "proceed"}


def test_an_already_parsed_value_passes_through_untouched() -> None:
    """The same value, not a copy — a JSON-typed transport (and every fake in
    the tests) hands back a dict that has already been decoded once."""
    parsed = {"verdict": "proceed"}
    assert parse_json_text(parsed) is parsed


def test_none_stays_none_rather_than_becoming_an_empty_dict() -> None:
    """A NULL column and a column holding ``"{}"`` are different facts.

    `get_report` distinguishes a report that has no scorecard from one whose
    scorecard is empty; collapsing them here would make a missing analysis look
    like a completed, blank one.
    """
    assert parse_json_text(None) is None


def test_a_non_string_scalar_passes_through() -> None:
    assert parse_json_text(7) == 7
    assert parse_json_text(True) is True


def test_malformed_text_still_raises() -> None:
    """Deliberately not swallowed. Every hand-written copy this replaced raised
    too, and a malformed body from Core is a real fault — returning `{}` here
    would turn a loud failure into a silently empty report."""
    with pytest.raises(json.JSONDecodeError):
        parse_json_text("not json at all")
