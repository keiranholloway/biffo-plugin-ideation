"""Pins the seeded model catalog's shape (scripts/seed_model_catalog.py)."""

from __future__ import annotations

from scripts.seed_model_catalog import _SEED_MODELS


def test_exactly_one_model_is_default() -> None:
    defaults = [m for m in _SEED_MODELS if m["is_default"]]
    assert len(defaults) == 1


def test_the_default_is_the_cheapest_seeded_model() -> None:
    default = next(m for m in _SEED_MODELS if m["is_default"])
    assert default["model_id"] == "deepseek/deepseek-v4-flash"


def test_every_seed_model_is_active() -> None:
    assert all(m["active"] for m in _SEED_MODELS)


def test_seed_catalog_has_between_four_and_six_models() -> None:
    assert 4 <= len(_SEED_MODELS) <= 6


def test_every_model_id_and_label_is_non_empty() -> None:
    for m in _SEED_MODELS:
        assert m["model_id"]
        assert m["label"]
