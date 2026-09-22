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


# --------------------------------------------------------------------------- #
# E4: poll-matrix (v2) gate rules
# --------------------------------------------------------------------------- #

def good_poll_matrix_products() -> dict:
    return {
        "generated_at": "2026-09-26T19:30:00+00:00",
        "precision": "full",
        "week": 9,
        "podium": {
            "winner": {"name": "A", "prob": 0.6},
            "runner_up": {"name": "B", "prob": 0.25},
            "second_runner_up": {"name": "C", "prob": 0.1},
        },
        "housemates": [
            {"name": "A", "status": "active", "p_rank_1": 0.7, "share": 0.5,
             "ci_89": [0.4, 0.6], "momentum": 0.1, "carried": False,
             "history": [{"week": 9, "median": 0.5, "hdi_89": [0.4, 0.6]}]},
            {"name": "B", "status": "active", "p_rank_1": 0.2, "share": 0.3,
             "ci_89": [0.22, 0.38], "momentum": None, "carried": True,
             "history": [{"week": 9, "median": 0.3, "hdi_89": [0.22, 0.38]}]},
            {"name": "C", "status": "active", "p_rank_1": 0.1, "share": 0.2,
             "ci_89": [0.14, 0.26], "momentum": None, "carried": False,
             "unmeasured": True,
             "history": [{"week": 9, "median": 0.2, "hdi_89": [0.14, 0.26]}]},
        ],
        "at_risk": [{"name": "C", "share": 0.2, "bottom_n_flag": True}],
        "engine": {"name": "poll_matrix",
                   "params": {"cap": 5000, "lambda_decay": 0.6}},
        "data_sufficiency": {"rows_in_window": 3, "full_share_rows": 2,
                             "constraint_rows": 1, "sources_reporting": ["bbnaijadaily"],
                             "weeks_in_window": [7, 8, 9]},
    }


def test_poll_matrix_valid_passes():
    assert validate_products(good_poll_matrix_products()) == []


def test_poll_matrix_share_sum_enforced():
    p = good_poll_matrix_products()
    p["housemates"][0]["share"] = 0.9     # 0.9 + 0.3 + 0.2 = 1.4
    with pytest.raises(SchemaError, match="shares must sum to 1"):
        validate_products(p)


def test_poll_matrix_missing_share_rejected():
    p = good_poll_matrix_products()
    del p["housemates"][0]["share"]
    with pytest.raises(SchemaError, match="share"):
        validate_products(p)


def test_poll_matrix_ci_ordering_enforced():
    p = good_poll_matrix_products()
    p["housemates"][0]["ci_89"] = [0.6, 0.4]   # inverted
    with pytest.raises(SchemaError, match="ci_89 must be ordered"):
        validate_products(p)


def test_poll_matrix_at_risk_share_shape_required():
    p = good_poll_matrix_products()
    p["at_risk"] = [{"name": "C", "relative_hazard": 1.5}]   # legacy shape
    with pytest.raises(SchemaError, match="numeric share"):
        validate_products(p)


def test_poll_matrix_engine_params_required():
    p = good_poll_matrix_products()
    p["engine"]["params"] = {}
    with pytest.raises(SchemaError, match="params"):
        validate_products(p)


def test_poll_matrix_rows_in_window_required():
    p = good_poll_matrix_products()
    p["data_sufficiency"]["rows_in_window"] = 0
    with pytest.raises(SchemaError, match="rows_in_window"):
        validate_products(p)


def test_poll_matrix_podium_allows_fewer_than_three_actives():
    p = good_poll_matrix_products()
    p["podium"] = {"winner": {"name": "A", "prob": 1.0},
                   "runner_up": {"name": None, "prob": 0.0},
                   "second_runner_up": {"name": None, "prob": 0.0}}
    p["housemates"] = p["housemates"][:1]     # 1 active only
    p["housemates"][0]["p_rank_1"] = 1.0
    p["housemates"][0]["share"] = 1.0
    assert validate_products(p) == []


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
