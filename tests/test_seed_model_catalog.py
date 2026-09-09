"""Pins the seeded model catalog's shape (scripts/seed_model_catalog.py)."""

from __future__ import annotations

from scripts.seed_model_catalog import _BASE_SEED_MODELS, _SEED_MODELS, ONLINE_SUFFIX


def test_exactly_one_model_is_default() -> None:
    defaults = [m for m in _SEED_MODELS if m["is_default"]]
    assert len(defaults) == 1


def test_the_default_is_the_cheapest_seeded_model() -> None:
    default = next(m for m in _SEED_MODELS if m["is_default"])
    assert default["model_id"] == "deepseek/deepseek-v4-flash"


def test_every_seed_model_is_active() -> None:
    assert all(m["active"] for m in _SEED_MODELS)


def test_seed_catalog_has_between_eight_and_twelve_models() -> None:
    # Five plain + five ':online' siblings, paired (issue #92).
    assert 8 <= len(_SEED_MODELS) <= 12


def test_every_model_id_and_label_is_non_empty() -> None:
    for m in _SEED_MODELS:
        assert m["model_id"]
        assert m["label"]


# ── issue #92: web_capable ───────────────────────────────────────────────────


def test_every_base_model_has_an_online_sibling() -> None:
    seeded_ids = {m["model_id"] for m in _SEED_MODELS}
    for base in _BASE_SEED_MODELS:
        assert f"{base['model_id']}{ONLINE_SUFFIX}" in seeded_ids


def test_web_capable_agrees_with_the_online_suffix_on_every_seed_row() -> None:
    # web_capable is declared explicitly (biffo.plugin.json), not derived at
    # read time — but it must never disagree with the suffix it is derived
    # from at seed time, or the catalog lies about what it seeded.
    for m in _SEED_MODELS:
        assert m["web_capable"] == str(m["model_id"]).endswith(ONLINE_SUFFIX)


def test_no_online_sibling_is_the_catalog_default() -> None:
    # A default an agent silently inherits should not carry a live-search
    # cost per call.
    for m in _SEED_MODELS:
        if str(m["model_id"]).endswith(ONLINE_SUFFIX):
            assert not m["is_default"]


def test_no_base_model_is_web_capable() -> None:
    # The plain half of each pair must not claim search it does not have.
    for m in _BASE_SEED_MODELS:
        assert not m["web_capable"]
