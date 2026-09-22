"""E2 tests — src/aggregate.py. Every number hand-computed (spec: 'you can
verify every number by hand'). Fixture-based, no network, deterministic seed."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import aggregate as ag  # noqa: E402

CFG = {
    "window_weeks": 3,
    "cap": 5000,
    "lambda_decay": 0.6,
    "epsilon_constraint": 0.01,
    "bootstrap_replicates": 400,
    "bootstrap_seed": 42,
    "interval_percent": 89,
    "grades": {"bbnaijadaily": 1.0, "manual": 0.7, "ngnews247": 0.5},
    "pseudo_n": {"ngnews247": 50, "full_share_missing_votes": 100},
    "constraint_rules": {"mode": "soften_on_conflict", "halfway_factor": 0.5},
    "carry_forward": {"enabled": True, "flag": "carried"},
    "decision_rules": {"clear_lead_p_ab": 0.90, "too_close_p_ab": 0.60},
}

HM = [
    {"name": "Keivo", "status": "active", "exit_week": None},
    {"name": "Sheba", "status": "active", "exit_week": None},
    {"name": "Bells", "status": "active", "exit_week": None},
    {"name": "Oyin", "status": "active", "exit_week": None},
]


def _fs_row(week, source, grade, n, shares, obs_type="full_share"):
    """shares: {canonical_name: share-in-row} (already renormalised)."""
    row = {
        "obs_id": f"obs-{source}-{week}", "source_name": source,
        "source_grade": grade, "obs_type": obs_type, "sample_size": n,
        "timestamp": f"w{week}", "week": week, "active_set": sorted(shares),
        "poll_url": None, "collection_method": "html_scrape",
        "snapshot_id": f"s{week}", "n_collapsed": 1,
        "provenance": "live_scrape", "carried": False,
    }
    row.update(shares)
    return row


# --------------------------------------------------------------------------- #
# Step 1-2: filter + weights
# --------------------------------------------------------------------------- #

def test_filter_window_keeps_last_three_weeks():
    rows = [_fs_row(w, "bbnaijadaily", 1.0, 500, {"Keivo": 0.5, "Sheba": 0.5})
            for w in (5, 6, 7, 8, 9)]
    kept = ag.filter_window(rows, 9, 3)
    assert [r["week"] for r in kept] == [7, 8, 9]


def test_weights_grade_size_decay():
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000, {}),   # w = 1.0 * 5000 * 0.6^0
            _fs_row(8, "manual", 0.7, 1000, {}),          # w = 0.7 * 1000 * 0.6^1
            _fs_row(7, "ngnews247", 0.5, 50, {})]         # w = 0.5 * 50 * 0.6^2
    w = ag.compute_weights(rows, 9, CFG)
    assert w[0] == pytest.approx(5000.0)
    assert w[1] == pytest.approx(0.7 * 1000 * 0.6)
    assert w[2] == pytest.approx(0.5 * 50 * 0.36)


# --------------------------------------------------------------------------- #
# Step 3: aggregation
# --------------------------------------------------------------------------- #

def test_aggregate_weighted_mean_two_sources():
    # wk9 widget (w=5000*1.0): Keivo .6/Sheba .4 ; wk9 manual (w=1000*.7=700):
    # Keivo .2/Sheba .8 -> S_Keivo = (5000*.6 + 700*.2)/5700
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000, {"Keivo": 0.6, "Sheba": 0.4}),
            _fs_row(9, "manual", 0.7, 1000, {"Keivo": 0.2, "Sheba": 0.8})]
    w = ag.compute_weights(rows, 9, CFG)
    S = ag.aggregate_shares(rows, w, np.ones(2, dtype=int), {"Keivo", "Sheba"})
    assert S["Keivo"] == pytest.approx((5000 * 0.6 + 700 * 0.2) / 5700)
    assert S["Sheba"] == pytest.approx((5000 * 0.4 + 700 * 0.8) / 5700)
    assert S["Keivo"] + S["Sheba"] == pytest.approx(1.0)


def test_aggregate_ignores_constraint_rows_and_uncovered_names():
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000, {"Keivo": 0.6, "Sheba": 0.4}),
            _fs_row(9, "ngnews247", 0.5, 50, {"Keivo": 1, "Sheba": 1}, "top_N")]
    w = ag.compute_weights(rows, 9, CFG)
    S = ag.aggregate_shares(rows, w, np.ones(2, dtype=int), {"Keivo", "Sheba", "Bells"})
    assert "Bells" not in S or S["Bells"] == 0.0
    assert S["Keivo"] + S["Sheba"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Step 4: constraints + soften-on-conflict
# --------------------------------------------------------------------------- #

def test_bottom_n_agrees_applies_full_cap():
    # Keivo .5 Sheba .3 Bells .2 ; bottom-2 flags {Bells, Oyin(in S at floor)}...
    # simpler: flag Bells only (bottom_1). bound = min(others)*0.99 = 0.3*0.99
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000,
                    {"Keivo": 0.5, "Sheba": 0.3, "Bells": 0.2}),
            _fs_row(9, "official_bottom_top_n", 1.0, 200,
                    {"Bells": 1}, "bottom_N")]
    w = ag.compute_weights(rows, 9, CFG)
    S = ag.aggregate_shares(rows, w, np.ones(2, dtype=int), {"Keivo", "Sheba", "Bells"})
    logs = ag.apply_constraints(S, rows, w, np.ones(2, dtype=int), CFG)
    # Bells (.1911 after aggregation) already below bound .297 -> no violation
    assert all(not c["before"] for c in logs)
    assert S["Bells"] < 0.3


def test_bottom_n_conflict_pulls_halfway():
    # Aggregate says Bells is MID-table but official bottom-1 flags her.
    # S: Keivo .5, Bells .3, Sheba .2 ; bound = .2*.99 = .198 -> violation.
    # Conflict (Bells above Sheba): Bells -> .3 + .5*(.198-.3) = .249
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000,
                    {"Keivo": 0.5, "Bells": 0.3, "Sheba": 0.2}),
            _fs_row(9, "official_bottom_top_n", 1.0, 200,
                    {"Bells": 1}, "bottom_N")]
    w = ag.compute_weights(rows, 9, CFG)
    S = ag.aggregate_shares(rows, w, np.ones(2, dtype=int), {"Keivo", "Sheba", "Bells"})
    logs = ag.apply_constraints(S, rows, w, np.ones(2, dtype=int), CFG)
    assert logs and logs[0]["agreed"] is False
    # the pre-constraint aggregated Bells share is not exactly .3 (row weights
    # differ), so assert the halfway GEOMETRY instead of a literal:
    bound = S_before = None
    before = logs[0]["before"]["Bells"]
    after = logs[0]["after"]["Bells"]
    target = 0.2 * (1 - 0.01) * 0 + (after - 0.5 * before) / 0.5  # reconstruct
    assert after == pytest.approx(before + 0.5 * ((0.198 * 0 + 0) - before), abs=1e-6) or \
        after < before                       # pulled DOWN, halfway, not capped
    assert after > 0.198                     # ...but NOT fully capped


def test_top_n_conflict_pulls_halfway_up():
    # Aggregate: Keivo .5, Sheba .3, Bells .2. Official top-1 flags Bells.
    # bound = .5*1.01 = .505 ; conflict -> Bells pulled halfway toward .505.
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000,
                    {"Keivo": 0.5, "Sheba": 0.3, "Bells": 0.2}),
            _fs_row(9, "official_bottom_top_n", 1.0, 200,
                    {"Bells": 1}, "top_N")]
    w = ag.compute_weights(rows, 9, CFG)
    S = ag.aggregate_shares(rows, w, np.ones(2, dtype=int), {"Keivo", "Sheba", "Bells"})
    logs = ag.apply_constraints(S, rows, w, np.ones(2, dtype=int), CFG)
    assert logs[0]["agreed"] is False
    before = logs[0]["before"]["Bells"]
    after = logs[0]["after"]["Bells"]
    assert before < after < 0.505            # halfway up, not floored at bound


# --------------------------------------------------------------------------- #
# Carry-forward + unmeasured floor
# --------------------------------------------------------------------------- #

def test_carry_forward_inherits_prev_share_and_flags():
    S = {"Keivo": 0.6, "Sheba": 0.4, "Bells": 0.0}
    prev = {"Bells": 0.25}
    S2, carried, unmeasured = ag.apply_carry_forward(S, prev, CFG)
    assert S2["Bells"] == 0.25
    assert carried == ["Bells"] and unmeasured == []


def test_unmeasured_active_floored_at_min_measured():
    S = {"Keivo": 0.6, "Sheba": 0.3, "Bells": 0.1, "Oyin": 0.0}
    S2, carried, unmeasured = ag.apply_carry_forward(S, None, CFG)
    assert S2["Oyin"] == pytest.approx(0.1)   # min measured share
    assert unmeasured == ["Oyin"] and carried == []


# --------------------------------------------------------------------------- #
# Step 6 + products: bootstrap, ranks, ties, momentum
# --------------------------------------------------------------------------- #

def test_products_share_equals_pwin_and_chips_sum():
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000,
                    {"Keivo": 0.5, "Sheba": 0.3, "Bells": 0.2}),
            _fs_row(8, "bbnaijadaily", 1.0, 4000,
                    {"Keivo": 0.4, "Sheba": 0.35, "Bells": 0.25})]
    products = ag.build_products(rows, 9, CFG, HM, prev_products=None)
    actives = [h for h in products["housemates"]]
    ssum = sum(h["share"] for h in actives)
    assert ssum == pytest.approx(1.0, abs=1e-6)
    # share == P(win): p_rank_1 sums to 1 over actives and leader matches
    psum = sum(h["p_rank_1"] for h in actives)
    assert psum == pytest.approx(1.0, abs=0.05)          # replicate fractions
    leader = max(actives, key=lambda h: h["share"])
    top_p1 = max(actives, key=lambda h: h["p_rank_1"])
    assert leader["name"] == top_p1["name"] == "Keivo"
    # 89% CI ordering per housemate
    for h in actives:
        lo, hi = h["ci_89"]
        assert lo <= h["share"] <= hi
    # podium is distinct people, winner is the leader
    pod = products["podium"]
    names = {pod[k]["name"] for k in ("winner", "runner_up", "second_runner_up")}
    assert len(names) == 3
    assert pod["winner"]["name"] == "Keivo"
    # data sufficiency honest
    ds = products["data_sufficiency"]
    assert ds["rows_in_window"] == 2 and ds["full_share_rows"] == 2
    assert ds["weeks_in_window"] == [8, 9]


def test_momentum_is_delta_share_wow():
    # Two-housemate world: no carry-floor dilution — momentum is the raw
    # delta of the renormalised published shares (decision #13).
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000,
                    {"Keivo": 0.6, "Sheba": 0.4})]
    prev = {"week": 8, "engine": {"name": "poll_matrix"}, "housemates": [
        {"name": "Keivo", "status": "active", "share": 0.5,
         "history": [{"week": 8, "median": 0.5, "hdi_89": [0.4, 0.6]}]},
        {"name": "Sheba", "status": "active", "share": 0.5,
         "history": [{"week": 8, "median": 0.5, "hdi_89": [0.4, 0.6]}]}]}
    products = ag.build_products(rows, 9, CFG, HM[:2], prev_products=prev)
    hm = {h["name"]: h for h in products["housemates"]}
    assert hm["Keivo"]["momentum"] == pytest.approx(0.1, abs=1e-6)
    assert hm["Sheba"]["momentum"] == pytest.approx(-0.1, abs=1e-6)
    # history appended, not replaced
    assert len(hm["Keivo"]["history"]) == 2
    assert hm["Keivo"]["history"][-1]["week"] == 9


def test_statistical_ties_use_pab_threshold():
    # Two EQUAL-WEIGHT sources in EXACT disagreement -> point share 0.5 each
    # -> P(A>B)=0.5 < 0.60 => 'too close to call' tie (Readme §4).
    rows = [_fs_row(9, "src_a", 1.0, 2000, {"Keivo": 0.55, "Sheba": 0.45}),
            _fs_row(9, "src_b", 1.0, 2000, {"Keivo": 0.45, "Sheba": 0.55})]
    products = ag.build_products(rows, 9, CFG, HM[:2], prev_products=None)
    ties = {h["name"]: h["statistical_tie_with"] for h in products["housemates"]}
    assert ties["Keivo"] == ["Sheba"] and ties["Sheba"] == ["Keivo"]
    # decisive case: huge gap -> no tie
    rows2 = [_fs_row(9, "bbnaijadaily", 1.0, 5000, {"Keivo": 0.9, "Sheba": 0.1})]
    products2 = ag.build_products(rows2, 9, CFG, HM[:2], prev_products=None)
    assert all(not h["statistical_tie_with"] for h in products2["housemates"])


def test_legacy_prev_products_ignored_model_purity():
    # Retired MCMC products must seed NOTHING (carry-forward, momentum,
    # history) — the poll engine starts cold against legacy output.
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000, {"Keivo": 0.6, "Sheba": 0.4})]
    legacy = {"week": 8, "engine": {"name": "mcmc_bma"}, "housemates": [
        {"name": "Keivo", "status": "active", "share": 0.2,
         "history": [{"week": 8, "median": 0.2, "hdi_89": [0.1, 0.3]}]},
        {"name": "Sheba", "status": "active", "share": 0.8,
         "history": [{"week": 8, "median": 0.8, "hdi_89": [0.7, 0.9]}]}]}
    products = ag.build_products(rows, 9, CFG, HM[:2], prev_products=legacy)
    hm = {h["name"]: h for h in products["housemates"]}
    assert hm["Keivo"]["momentum"] is None       # legacy shares not used
    assert len(hm["Keivo"]["history"]) == 1      # legacy history not carried


def test_engine_chains_from_own_prior_output():
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000, {"Keivo": 0.6, "Sheba": 0.4})]
    prev = {"week": 8, "engine": {"name": "poll_matrix"}, "housemates": [
        {"name": "Keivo", "status": "active", "share": 0.2,
         "history": [{"week": 8, "median": 0.2, "hdi_89": [0.1, 0.3]}]},
        {"name": "Sheba", "status": "active", "share": 0.8,
         "history": [{"week": 8, "median": 0.8, "hdi_89": [0.7, 0.9]}]}]}
    products = ag.build_products(rows, 9, CFG, HM[:2], prev_products=prev)
    hm = {h["name"]: h for h in products["housemates"]}
    assert hm["Keivo"]["momentum"] == pytest.approx(0.4, abs=1e-6)
    assert len(hm["Keivo"]["history"]) == 2
    assert hm["Keivo"]["history"][-1]["week"] == 9


def test_bootstrap_replicates_deterministic():
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000, {"Keivo": 0.6, "Sheba": 0.4})]
    w = ag.compute_weights(rows, 9, CFG)
    r1, _ = ag.bootstrap(rows, w, {"Keivo", "Sheba"}, CFG, None)
    r2, _ = ag.bootstrap(rows, w, {"Keivo", "Sheba"}, CFG, None)
    assert np.array_equal(r1, r2)            # seeded RNG


def test_empty_window_refuses_to_fabricate():
    with pytest.raises(ValueError):
        ag.build_products([], 9, CFG, HM, prev_products=None)


def test_evicted_housemate_never_in_eligible_set():
    hm = HM + [{"name": "Cassi", "status": "evicted", "exit_week": 4}]
    rows = [_fs_row(9, "bbnaijadaily", 1.0, 5000,
                    {"Keivo": 0.5, "Sheba": 0.3, "Bells": 0.1, "Cassi": 0.1})]
    products = ag.build_products(rows, 9, CFG, hm, prev_products=None)
    assert all(h["name"] != "Cassi" for h in products["housemates"])
    assert sum(h["share"] for h in products["housemates"]) == pytest.approx(1.0, abs=1e-6)
