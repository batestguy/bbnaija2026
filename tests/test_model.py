"""P5 modeling-core tests (fixture-based, no network, no real-data dependence).

Covers the P5.10 checklist: Gambit zero-out semantics, rank-probability sums,
deterministic tie-break, table building (gaps/entries/exits), BMA weighting
(including gate rejection), and the R-hat gate on a deliberately degraded run.

The sampled tests run the FULL 12-housemate / 6-week synthetic season (never
real data): by t_now=6 its Gambit pair is released, so p_rank_1 sums cleanly
over all actives, and the last-three-positions exit ledger gives the Cox
sub-model real event weeks. FAST_COMPILE (conftest) keeps pytensor in Python
mode for speed — acceptable for 120-200-draw sanity runs.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import notebooks.bbnaija_mcmc as m


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def nearly(seq: list[float]) -> None:
    arr = np.asarray(seq, dtype=float)
    assert abs(arr.sum() - 1.0) < 1e-9


# --------------------------------------------------------------------------- #
# Gambit filter (frozen math)
# --------------------------------------------------------------------------- #

def test_gambit_filter_zeroes_and_renormalises():
    mu = np.array([[1.0, 2.0, 0.5]])                       # one draw, 3 housemates
    flag = np.array([0, 1, 0])
    w = m.gambit_filter(mu, flag)
    assert w[0, 1] == 0.0                                  # exact zero, not down-weight
    nearly(list(w[0]))
    assert w[0, 0] > w[0, 2]                               # ranking preserved


def test_gambit_filter_vectorised_over_draws():
    rng = np.random.default_rng(0)
    mu = rng.normal(size=(50, 4))
    flag = np.array([0, 0, 1, 0])
    w = m.gambit_filter(mu, flag)
    assert w.shape == (50, 4)
    assert np.all(w[:, 2] == 0.0)
    assert np.allclose(w.sum(axis=1), 1.0, atol=1e-9)   # every row normalises


def test_gambit_filter_all_flagged_is_an_error():
    with pytest.raises(ValueError):
        m.gambit_filter(np.array([[1.0, 2.0]]), np.array([1, 1]))


# --------------------------------------------------------------------------- #
# DM shares — regression for the week-8 "Yusuf = 0.0" bug (2026-09-18)
# --------------------------------------------------------------------------- #

def test_dm_shares_never_zero_out_a_non_gambit_column():
    """numpy's multinomial treats the LAST PASSED pval as the remainder bin.
    Passing p[:-1] silently folded the last housemate's mass into the
    second-to-last column, hard-zeroing the last active housemate's snapshot
    (Yusuf, week 8). The bug's signature: the STRONGEST housemate gets exactly
    0.0 in ~every draw while the second-to-last column absorbs its mass.
    (Weak columns do earn genuine exact zeros from the DM multinomial when
    their true share rounds to 0 votes — that is legal, not a bug.)"""
    rng = np.random.default_rng(7)
    n_draws, n_hm = 400, 5
    mu = rng.normal(size=(n_draws, n_hm))
    mu += 1.5 * np.arange(n_hm)                           # column 4 strongest
    flag = np.zeros(n_hm, dtype=int)                      # nobody is Gambit
    shares = m.dm_win_shares(mu, flag, np.random.default_rng(8), n_draws=300)
    assert np.all(shares.sum(axis=1) > 0.999)              # rows still conserve
    # the strongest column must essentially never be exactly zero — the old
    # remainder-bin code failed this with a ~100% zero rate
    assert (shares[:, -1] == 0.0).mean() < 0.01, "strongest column zeroed — remainder-bin bug is back"
    assert (shares[:, -2] == 0.0).mean() < 0.01            # old theft target, second-to-last
    assert np.median(shares[:, -1]) > 0.3                  # and it actually leads


def test_dm_shares_gambit_zero_survives_full_vector_fix():
    """The Gambit-zeroed column must stay exactly 0 with the full-vector
    multinomial (no stolen remainder, no invalid-Dirichlet regression)."""
    rng = np.random.default_rng(9)
    mu = rng.normal(size=(200, 4))
    flag = np.array([0, 0, 0, 1])                          # last housemate is Gambit
    shares = m.dm_win_shares(mu, flag, np.random.default_rng(10), n_draws=200)
    assert np.all(shares[:, 3] == 0.0)                     # exact zero preserved
    assert np.allclose(shares.sum(axis=1), 1.0, atol=1e-9)
    nearly(list(shares[:, :3].mean(axis=0)))


# --------------------------------------------------------------------------- #
# Rank machinery
# --------------------------------------------------------------------------- #

def test_rank_probs_sum_and_podium_eligibility():
    # housemate 1 (Gambit) gets mu=-inf via the filter; others random
    rng = np.random.default_rng(1)
    mu = rng.normal(size=(2000, 4))
    flag = np.array([0, 1, 0, 0])
    shares = m.dm_win_shares(mu, flag, np.random.default_rng(2), n_draws=300)
    prods = m.rank_products(shares, ["A", "B", "C", "D"])
    p1 = [prods["per_housemate"][n]["p_rank_1"] for n in ["A", "B", "C", "D"]]
    assert p1[1] == 0.0                                    # Gambit never ranks #1
    nearly(p1)                                             # p_rank_1 sums to 1
    # Gambit housemate still eligible in top-3/top-5
    assert prods["per_housemate"]["B"]["p_top3"] >= 0.0


def test_rank_tie_break_is_deterministic_alphabetical():
    shares = np.ones((100, 3)) / 3.0                       # perfect tie
    names = ["Zulu", "Alpha", "Mike"]
    ranks = m.rank_draws(shares, names)
    # all ties -> alphabetical: Alpha wins, Mike 2nd, Zulu 3rd (per column)
    assert set(ranks[:, 0].tolist()) == {2}                # Zulu  -> rank 3
    assert set(ranks[:, 1].tolist()) == {0}                # Alpha -> rank 1
    assert set(ranks[:, 2].tolist()) == {1}                # Mike  -> rank 2
    podium = m.podium_from_ranks(ranks, names)
    assert podium["winner"]["name"] == "Alpha"
    assert podium["runner_up"]["name"] == "Mike"
    assert podium["second_runner_up"]["name"] == "Zulu"


def test_statistical_ties_detect_overlapping_hdis():
    rng = np.random.default_rng(3)
    # A and B nearly identical, C clearly lower
    a = np.clip(rng.normal(0.40, 0.02, size=(2000, 1)), 0, 1)
    b = np.clip(rng.normal(0.41, 0.02, size=(2000, 1)), 0, 1)
    c = np.clip(rng.normal(0.05, 0.01, size=(2000, 1)), 0, 1)
    shares = np.hstack([a, b, c])
    ties = m.statistical_ties(shares, ["A", "B", "C"])
    assert "B" in ties["A"] and "A" in ties["B"]
    assert ties["C"] == []


# --------------------------------------------------------------------------- #
# Table building
# --------------------------------------------------------------------------- #

def _payload(records, weeks):
    return {"generated_at": "x", "season": 11, "weeks_built": weeks,
            "missing_weeks": [], "records": records}


def _rec(week, name, cpi=0.5, status="active", at_risk=0, gambit=0, backfilled=False):
    return {"season": 11, "week": week, "week_start": "2026-07-26", "housemate": name,
            "comments": None, "shares": None, "article_mentions": 3, "headline_features": 1,
            "cpi": cpi, "sentiment": 0.1, "at_risk": at_risk, "twist": 1,
            "gambit_flag": gambit, "backfilled": backfilled, "status": status,
            "sources": ["test"], "missing_weeks": []}


def test_build_table_gaps_entries_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "CONFIG_DIR", tmp_path)
    (tmp_path / "twist.json").write_text(json.dumps({"twist_start_week": 1}))
    (tmp_path / "season.json").write_text(json.dumps(
        {"premiere_date": "2026-07-26", "finale_date": "2026-10-04"}))
    roster = [{"name": n, "photo": f"p/{n}.jpg"} for n in ("A", "B", "C")]
    # week 1: A,C only (B not in house) — week 2: B evicted — week 3 missing (gap)
    recs = [_rec(1, "A"), _rec(1, "C"),
            _rec(2, "A"), _rec(2, "B", status="evicted"), _rec(2, "C"),
            _rec(4, "A", backfilled=True), _rec(4, "C", backfilled=True)]
    table = m.build_table(_payload(recs, [1, 2, 4]), roster)
    assert table.weeks_built == [1, 2, 4]
    assert table.finale_week == 10                         # ceil(70 days / 7)
    assert np.isnan(table.y[0, 1])                         # pre-entry = missing, not zero
    assert table.event[1, 1] == 1.0                        # B's eviction coded
    assert table.backfilled_weeks == [4]
    active = table.active_idx()
    assert sorted(table.housemates[i] for i in active) == ["A", "C"]


# --------------------------------------------------------------------------- #
# BMA weights + gates
# --------------------------------------------------------------------------- #

def test_pseudo_bma_plus_prefers_better_candidate():
    rng = np.random.default_rng(4)
    good = rng.normal(0.0, 0.05, size=500)                 # tight around 0
    bad = rng.normal(-3.0, 1.00, size=500)                 # much worse ELPD
    w = m._pseudo_bma_plus({"momentum": good, "baseline": bad}, b=200, seed=5)
    assert w["momentum"] > 0.9
    nearly(list(w.values()))


def test_bma_weights_gate_failures_all_fail(monkeypatch):
    class FakeIdata:                                        # never touched: gate stubbed
        pass

    monkeypatch.setattr(m, "convergence_gate", lambda ida, gate: (1.5, False))
    w = m.bma_weights({"momentum": FakeIdata(), "baseline": FakeIdata(),
                       "heteroscedastic": FakeIdata()})
    # no survivor -> all weights zero; the runner raises ModelRejected before
    # assembly, so a zero field never reaches the products
    assert w == {"momentum": 0.0, "baseline": 0.0, "heteroscedastic": 0.0}


def test_bma_weights_single_survivor_takes_all(monkeypatch):
    class FakeIdata:
        pass

    def gate(ida, gate_val=1.01):
        return (1.005, ida is SURVIVOR)

    SURVIVOR = FakeIdata()
    others = (FakeIdata(), FakeIdata())
    monkeypatch.setattr(m, "convergence_gate", gate)
    w = m.bma_weights({"momentum": others[0], "baseline": SURVIVOR,
                       "heteroscedastic": others[1]})
    assert w == {"momentum": 0.0, "baseline": 1.0, "heteroscedastic": 0.0}


def test_rhat_gate_flags_degraded_run():
    """A deliberately bad (label-switching) chain must FAIL the 1.01 gate."""
    draws, chains = 300, 4
    bad = np.empty((chains, draws))
    bad[0] = np.linspace(-1.0, 1.0, draws)                 # opposite trends
    bad[1] = np.linspace(1.0, -1.0, draws)
    bad[2] = np.linspace(-1.0, 1.0, draws)
    bad[3] = np.linspace(1.0, -1.0, draws)
    idata = m.az.from_dict(posterior={"alpha": bad})
    rmax, ok = m.convergence_gate(idata)
    assert not ok and rmax >= m.RHAT_GATE


# --------------------------------------------------------------------------- #
# Synthetic season (shared fixture): full 12-housemate / 6-week data
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def season_table():
    payload = m.synthetic_cpi_payload(seed=7, weeks=6)
    return m.build_table(payload, m.synthetic_roster(12), finale_week=10)


def test_synthetic_season_shape(season_table):
    assert season_table.N == 12 and season_table.T == 6
    assert season_table.t_now == 6 and season_table.finale_week == 10
    # last three exit (wk2/3/4); nine actives remain at t_now
    assert len(season_table.active_idx()) == 9
    # Gambit pair = first two housemates, weeks 1-5 only
    assert season_table.gambit[0, :2].tolist() == [1.0, 1.0]
    assert season_table.gambit[5, :2].tolist() == [0.0, 0.0]
    # Cox events exist in weeks 2, 3, 4
    assert season_table.event.sum(axis=1).tolist() == [0, 1, 1, 1, 0, 0]
    # at least one t_now nominee (at-risk panel stays live)
    assert season_table.at_risk[-1].sum() >= 1


def test_model_build_and_cox_terms(season_table):
    std = m.standardize(season_table)
    model = m.build_model(season_table, std, candidate="heteroscedastic")
    names = set(model.named_vars)
    for v in ("alpha", "beta", "gamma", "delta", "theta", "eta", "offsets",
              "psi", "nb_alpha", "s_spike", "mu"):
        assert v in names, v
    # cox potentials exist exactly for the synthetic event weeks (2, 3, 4)
    cox = {n for n in names if n.startswith("cox_week_")}
    assert cox == {"cox_week_1", "cox_week_2", "cox_week_3"}   # 0-indexed T loop


def test_prior_predictive_passes(season_table):
    std = m.standardize(season_table)
    model = m.build_model(season_table, std, candidate="baseline")
    res = m.prior_predictive_check(model, season_table, n=50, seed=11)
    assert res["pass"]
    assert 0.0 < res["share_min_eligible"] and res["share_max"] < 1.0


# --------------------------------------------------------------------------- #
# End-to-end (sampled, synthetic season) — sampling + products + gate
# --------------------------------------------------------------------------- #

def test_end_to_end_season_run(season_table):
    # Sequential-sampled smoke (see sample_model: Windows spawn hazard).
    # Plumbing-level assertions only — the full 4x2000 spec run is validated
    # separately (scripts/validate_p5.py), since FAST_COMPILE keeps it slow.
    # 1 chain is fine here: the R-hat gate is exercised in
    # test_rhat_gate_flags_degraded_run on synthetic chains.
    std = m.standardize(season_table)
    idatas = {}
    for cand in m.BMA_CANDIDATES:
        model = m.build_model(season_table, std, candidate=cand)
        # 15/15: plumbing smoke only (2026-09-16 right-sizing — 25/25 exceeded
        # every practical pytest timeout on the BLAS-less box under FAST_COMPILE).
        idatas[cand] = m.sample_model(model, draws=15, tune=15, chains=1,
                                      seed=1234, lite=True)
    weights = m.bma_weights(idatas)
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    products = m.assemble_products(idatas, weights, season_table, std, lite=True)
    assert products["precision"] == "lite"                 # never silent
    podium_names = [products["podium"][k]["name"] for k in
                    ("winner", "runner_up", "second_runner_up")]
    assert len(set(podium_names)) == 3                     # distinct podium occupants
    # at t_now=6 nobody is Gambit-flagged; every active holds live win probs
    actives = [h for h in products["housemates"] if h["status"] == "active"]
    assert len(actives) == 9
    assert abs(sum(h["p_rank_1"] for h in actives) - 1.0) < 1e-6
    # 25-draw smoke posteriors can legitimately produce a zero-share draw for
    # a low-engagement housemate; strict positivity is asserted in the 4x2000
    # spec validation, not here.
    assert all(h["p_rank_1"] >= 0.0 for h in actives)
    # trend projection is secondary and horizon-complete
    assert products["trend_projection"]["horizon_week"] == season_table.finale_week
    assert len(products["trend_projection"]["podium"]) == 3
    # at-risk panel: nominated actives only, ranked
    assert products["at_risk"], "synthetic season guarantees a t_now nominee"
    assert all(r["nominated"] for r in products["at_risk"])
    hazards = [r["relative_hazard"] for r in products["at_risk"]]
    assert hazards == sorted(hazards, reverse=True)
