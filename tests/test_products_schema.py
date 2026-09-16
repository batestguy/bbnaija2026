"""Schema-gate tests (P6.3 step 1 / P8.2): pure python, no sampling, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.products_schema import SchemaError, validate_products

ROOT = Path(__file__).resolve().parents[1]


def good_products() -> dict:
    return {
        "generated_at": "2026-09-16T00:00:00+00:00",
        "precision": "full",
        "podium": {
            "winner": {"name": "A", "prob": 0.4},
            "runner_up": {"name": "B", "prob": 0.3},
            "second_runner_up": {"name": "C", "prob": 0.2},
        },
        "housemates": [
            {"name": "A", "status": "active", "p_rank_1": 0.5,
             "history": [{"week": 1, "median": 0.3, "hdi_89": [0.1, 0.5]}]},
            {"name": "B", "status": "active", "p_rank_1": 0.3,
             "history": [{"week": 1, "median": 0.2, "hdi_89": [0.05, 0.4]}]},
            {"name": "C", "status": "active", "p_rank_1": 0.2,
             "history": [{"week": 1, "median": 0.1, "hdi_89": [0.01, 0.3]}]},
            {"name": "D", "status": "evicted", "p_rank_1": 0.0,
             "history": [{"week": 1, "median": 0.05, "hdi_89": [0.0, 0.1]}]},
        ],
    }


def test_valid_product_passes():
    assert validate_products(good_products()) == []


def test_missing_required_field_rejected():
    p = good_products()
    del p["podium"]
    with pytest.raises(SchemaError, match="podium"):
        validate_products(p)


def test_bad_precision_rejected():
    p = good_products()
    p["precision"] = "best-guess"
    with pytest.raises(SchemaError, match="precision"):
        validate_products(p)


def test_duplicate_podium_names_rejected():
    p = good_products()
    p["podium"]["runner_up"]["name"] = "A"
    with pytest.raises(SchemaError, match="distinct"):
        validate_products(p)


def test_rank_probabilities_must_sum_to_one():
    p = good_products()
    for h in p["housemates"]:
        h["p_rank_1"] = 0.9
    with pytest.raises(SchemaError, match="sum to 1"):
        validate_products(p)


def test_gambit_winner_rejected():
    p = good_products()
    p["housemates"][0]["gambit_flag"] = 1
    with pytest.raises(SchemaError, match="Gambit"):
        validate_products(p)


def test_gambit_nonzero_rank1_rejected():
    p = good_products()
    p["housemates"][0]["gambit_flag"] = 1
    p["podium"]["winner"]["name"] = "B"
    p["podium"]["runner_up"]["name"] = "A"
    with pytest.raises(SchemaError, match="p_rank_1 == 0"):
        validate_products(p)


def test_bad_rhat_rejected():
    p = good_products()
    p["rhat_max"] = 1.02
    with pytest.raises(SchemaError, match="1.01"):
        validate_products(p)


def test_placeholder_requires_prior_predictive_label():
    p = good_products()
    p["placeholder"] = True
    with pytest.raises(SchemaError, match="prior-predictive"):
        validate_products(p)


def test_stale_generated_at_warns_but_passes():
    p = good_products()
    p["generated_at"] = "2026-01-01T00:00:00+00:00"
    warns = validate_products(p)
    assert any("stale" in w for w in warns)


def test_committed_placeholder_passes_gate():
    """The file the deploy workflow validates must always pass its own gate."""
    data = json.loads((ROOT / "docs" / "predictions.json").read_text(encoding="utf-8"))
    assert validate_products(data) == [] or data.get("placeholder") is True
