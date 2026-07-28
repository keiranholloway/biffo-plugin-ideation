"""The agent definitions: prompts, scored axes, and structured-output schema."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ideation.definitions import (
    MAX_TURNS,
    MIN_TURNS,
    PRD,
    REPORT_TOOL_NAME,
    Report,
    ScoreAxis,
    Scorecard,
    analyst_definition,
    challenger_definition,
    report_tool_schema,
)


def test_scorecard_covers_every_requested_axis() -> None:
    fields = Scorecard.model_fields
    for axis in ("viability", "complexity", "economic_moat", "market_fit"):
        assert axis in fields, axis
    # …plus the competitive/build-vs-buy view the founder asked for.
    assert "build_vs_buy" in fields
    assert "competitors" in fields
    assert "summary" in fields


def test_scores_are_bounded_one_to_five() -> None:
    ScoreAxis(score=1, rationale="ok")
    ScoreAxis(score=5, rationale="ok")
    with pytest.raises(ValidationError):
        ScoreAxis(score=0, rationale="too low")
    with pytest.raises(ValidationError):
        ScoreAxis(score=6, rationale="too high")


def test_challenger_is_a_single_turn_conversation_agent() -> None:
    d = challenger_definition(model="anthropic/claude-sonnet-4")
    assert d["tools"] == []  # conversation only, no tools
    assert d["max_turns"] == 1  # one reply per user message; the 3–5 cap is the session's
    instr = d["instructions"].lower()
    assert "one question per turn" in instr
    assert str(MAX_TURNS) in d["instructions"] and str(MIN_TURNS) in d["instructions"]


def test_analyst_researches_then_returns_structured_output() -> None:
    d = analyst_definition(model="anthropic/claude-opus-4.8:online")
    # No registry tools at all. web_search is only offered when the deployment has
    # a Brave credential; dev has none, so declaring it got the tool dropped
    # silently and left the analyst instructed to use something it never had.
    # Search now rides on the model slug's :online suffix instead.
    assert "tools" not in d
    assert REPORT_TOOL_NAME not in d.get("tools", [])
    assert report_tool_schema()["function"]["name"] == REPORT_TOOL_NAME
    instr = d["instructions"].lower()
    assert "build-vs-buy" in instr
    assert "competitive landscape" in instr
    # The prompt must not name a tool the runtime does not offer, and must forbid
    # passing off recalled competitors as research when no results arrive.
    assert "web_search" not in instr
    assert "unverified" in instr


def test_report_tool_schema_is_the_report_model() -> None:
    schema = report_tool_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == REPORT_TOOL_NAME
    params = schema["function"]["parameters"]
    assert set(params["properties"]) >= {"prd", "scorecard"}
    # It must be serialisable — it's sent to the provider verbatim.
    json.dumps(schema)


def test_report_round_trips() -> None:
    report = Report(
        prd=PRD(problem="Independent coaches can't manage clients + payments in one place."),
        scorecard=Scorecard(
            viability=ScoreAxis(score=4, rationale="Real recurring pain."),
            complexity=ScoreAxis(score=3, rationale="CRUD + payments; moderate."),
            economic_moat=ScoreAxis(score=2, rationale="Low switching costs."),
            market_fit=ScoreAxis(score=4, rationale="Large fragmented market."),
            build_vs_buy="Build — existing tools don't fit the coaching workflow.",
            competitors=[],
            summary="Promising; defensibility is the open question.",
        ),
    )
    assert report.scorecard.viability.score == 4
    assert report.prd.problem.startswith("Independent coaches")


def test_manifest_declares_the_owner_scoped_tables() -> None:
    manifest = json.loads((Path(__file__).resolve().parents[1] / "biffo.plugin.json").read_text())
    tables = {t["name"] for t in manifest["tables"]}
    assert {"ideation_sessions", "ideation_reports"} <= tables
    session_cols = {
        c["name"]
        for t in manifest["tables"]
        if t["name"] == "ideation_sessions"
        for c in t["columns"]
    }
    assert "thread_id" in session_cols  # transcript lives in the run thread, not a messages table
    assert "ideation_messages" not in tables


def test_scorecard_coerces_an_over_structured_build_vs_buy_to_a_string() -> None:
    """The output-tool schema says build_vs_buy is a string, but the model sometimes
    returns a dict like {"build": "hybrid", "text": "..."}. That must not 502 the
    whole report — flatten it to a sentence (regression for the live 502)."""
    from ideation.definitions import Report

    report = Report.model_validate(
        {
            "prd": {"problem": "p"},
            "scorecard": {
                "viability": {"score": 3, "rationale": "r"},
                "complexity": {"score": 3, "rationale": "r"},
                "economic_moat": {"score": 3, "rationale": "r"},
                "market_fit": {"score": 3, "rationale": "r"},
                "build_vs_buy": {"build": "hybrid", "text": "Lean on existing tools first."},
                "summary": "ok",
            },
        }
    )
    assert isinstance(report.scorecard.build_vs_buy, str)
    assert "Hybrid" in report.scorecard.build_vs_buy
    assert "Lean on existing tools first." in report.scorecard.build_vs_buy


def test_scorecard_leaves_a_plain_string_build_vs_buy_untouched() -> None:
    from ideation.definitions import Report

    report = Report.model_validate(
        {
            "prd": {"problem": "p"},
            "scorecard": {
                "viability": {"score": 3, "rationale": "r"},
                "complexity": {"score": 3, "rationale": "r"},
                "economic_moat": {"score": 3, "rationale": "r"},
                "market_fit": {"score": 3, "rationale": "r"},
                "build_vs_buy": "Build it — nothing off the shelf fits.",
                "summary": "ok",
            },
        }
    )
    assert report.scorecard.build_vs_buy == "Build it — nothing off the shelf fits."
