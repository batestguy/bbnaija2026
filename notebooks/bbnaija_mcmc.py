"""BBNaija 2026 Predictor — P5 modeling core (the committed run record).

The weekly model per PLAN.md §4 + weekly-standings-spec.md §3, implemented as a
script (not a notebook) so the committed file *is* the reproducible run record
(seeds fixed below; every prior logged and echoed into the run record).

Model
-----
Count sub-model (frozen, byte-for-byte):
    log(mu_it) = alpha + alpha_i + (beta + beta_i) * t + gamma*Sentiment
                 + delta*AtRisk + theta*Twist + eta*(Twist_it * beta_i)
with y_it = round(100 * CPI) modelled as ZeroInflatedNegativeBinomial (CPI is a
min-max-normalised index, so counts are a 0-100 "engagement points" scale).

Survival sub-model: Cox partial likelihood across weekly risk sets (risk set =
all housemates in the house that week; events = evicted/walked/disqualified
rows that week). Frailty alpha_i is SHARED with the count sub-model (the joint
"ZINB + Cox" model). Relative hazards only — no absolute eviction probabilities.

Priors (weakly-informative, spec D5/D15): predictors standardized first
(means/scales stored in the run record); fixed effects Normal(0, 2.5); variance
components HalfNormal(1) (alpha-column) and HalfNormal(candidate-specific) on
the beta-column — momentum 2.0 / baseline 0.5 / heteroscedastic 1.0, i.e. the
BMA candidates differ in their offsets prior as specced; correlations LKJ(2).
Additions (logged + recorded): NB dispersion HalfNormal(1), zero-inflation psi
Beta(2, 2). No show-history priors; current season only.

Gambit filter (frozen, byte-for-byte, applied in posterior predictive):
    WinProb_i = 0.0 if GambitFlag_i == 1 else exp(mu_i) / sum_{j not in Gambit} exp(mu_j)
Gambit housemates: P(#1) == 0 exactly, but remain runner-up/top-3/top-5 eligible.

Ranking machinery (from existing posterior draws — no new MCMC sampling):
10,000 Dirichlet-Multinomial posterior predictive draws -> per-housemate medians
+ 89% HDIs -> p_rank_1 / p_top3 / p_top5, podium slot probabilities, statistical
tie markers (overlapping adjacent 89% HDIs, alphabetical tie-break), and a
SECONDARY trend-projected podium (beta_i momentum extrapolation to the finale
with horizon-scaled uncertainty; never merged into the headline snapshot).

BMA: 3 candidates — momentum-heavy / baseline-heavy / post-Twist heteroscedastic
sigma^2_beta spike — weighted by Pseudo-BMA+ (ArviZ LOO ELPD, Bayesian-bootstrap
flavour). Weights recorded; headline model keeps the frozen formula.

Gates: R-hat < 1.01 else the run is rejected (caller keeps the last good
predictions.json and flags staleness). `lite` mode reduces draws and is always
labelled — never silent.

Usage:
    python notebooks/bbnaija_mcmc.py --selftest            # tiny synthetic end-to-end
    python notebooks/bbnaija_mcmc.py --synthetic --full    # P5 exit-criteria run
    python notebooks/bbnaija_mcmc.py --prior-check         # prior predictive sanity
    python notebooks/bbnaija_mcmc.py                       # real data, weeks built so far

Writes only under notebooks/ (single-writer rule: data/ belongs to run_weekly).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import arviz as az
import numpy as np
import pymc as pm

LOG = logging.getLogger("bbnaija_mcmc")

ROOT = Path(__file__).resolve().parents[1]
DAILY_CPI = ROOT / "data" / "processed" / "daily_cpi.json"
CONFIG_DIR = ROOT / "config"
RUN_RECORD_DIR = ROOT / "notebooks"  # run records live here, never under data/

# ---- Frozen constants ------------------------------------------------------
COUNT_SCALE = 100.0        # y = round(CPI * 100): "engagement points"
N_DM_DRAWS = 10_000        # posterior predictive draws for the rank machinery
NOMINAL_VOTES = 1_000_000  # multinomial size inside each DM draw
DM_CONCENTRATION = 50.0    # Dirichlet concentration kappa around the share vector
RHAT_GATE = 1.01
HDI_PROB = 0.89
MASTER_SEED = 20260912

PRIORS = {
    "fixed_effects": "Normal(0, 2.5)",
    "variance": "HalfNormal(1) on alpha-column sd; HalfNormal(candidate-specific) on beta-column sd (non-centered offsets)",
    "correlation": "LKJ(2)",
    "standardized": True,
    # documented additions to the three named families (auditability rule):
    "nb_dispersion": "HalfNormal(1)",
    "zero_inflation_psi": "Beta(2, 2)",
    "candidate_beta_column_sd": {"momentum": "HalfNormal(2.0)", "baseline": "HalfNormal(0.5)",
                                 "heteroscedastic": "HalfNormal(1.0)"},
    "count_scale": f"y = round(CPI * {COUNT_SCALE:.0f}); Dirichlet concentration {DM_CONCENTRATION}",
    # Poll-anchored prior (owner decision 2026-09-20). Values mirror
    # src/scrape_polls.py KAPPA/ANCHOR_CLIP — keep the two in sync.
    "poll_anchor": "alpha-column location shift m_i = 0.25 * clip(log(s_i * n), ±log 4); "
                   "midweek snapshot only; backfilled finals never anchor",
}

BMA_CANDIDATES = ("momentum", "baseline", "heteroscedastic")


class ModelRejected(RuntimeError):
    """Raised when the R-hat gate fails; the caller keeps the last good file."""


# --------------------------------------------------------------------------- #
# Data table
# --------------------------------------------------------------------------- #

@dataclass
class SeasonTable:
    """Model-ready arrays for one season snapshot (weeks 1..T observed)."""
    housemates: list[str]
    weeks_built: list[int]
    t_now: int                      # last observed week (the snapshot week)
    finale_week: int
    y: np.ndarray                   # (T, N) counts, NaN where not in house
    sent: np.ndarray                # (T, N) sentiment, NaN -> mean downstream
    at_risk: np.ndarray             # (T, N) 0/1 nomination facts
    twist: np.ndarray               # (T,) 0/1
    gambit: np.ndarray              # (T, N) 0/1 weekly-varying flags
    event: np.ndarray               # (T, N) 1 on exit week (evicted/walked/dq)
    status_now: dict[str, str]      # name -> week-relative status at t_now
    season: int
    week_start: str | None
    photos: dict[str, str] = field(default_factory=dict)
    missing_weeks: list[int] = field(default_factory=list)
    backfilled_weeks: list[int] = field(default_factory=list)

    @property
    def T(self) -> int:
        return len(self.weeks_built)

    @property
    def N(self) -> int:
        return len(self.housemates)

    def active_idx(self) -> np.ndarray:
        """Indices still in the running at t_now (status == 'active')."""
        return np.array([i for i, n in enumerate(self.housemates)
                         if self.status_now.get(n) == "active"], dtype=int)

    def in_house(self) -> np.ndarray:
        return ~np.isnan(self.y)


def load_twist_start_week() -> int:
    """twist_start_week read only from config/twist.json (never hardcoded)."""
    with open(CONFIG_DIR / "twist.json", encoding="utf-8") as fh:
        twist = json.load(fh)
    start = twist.get("twist_start_week")
    return 1 if start is None else int(start)


def load_poll_anchor(week: int) -> dict[str, Any] | None:
    """Archived poll snapshot for `week` (written by the run_weekly poll stage
    via src/scrape_polls.py). Only snapshot_type='midweek' may anchor the
    prior: backfilled 'final' snapshots are post-close data and must never
    feed the likelihood (outcome-leakage rule, 2026-09-20)."""
    path = ROOT / "data" / "raw" / f"week_{week:02d}" / "polls_snapshot.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            snap = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        LOG.warning("poll snapshot unreadable (%s): %s", path, e)
        return None
    if snap.get("snapshot_type", "midweek") != "midweek":
        LOG.info("poll snapshot wk%d is %r (backfilled) — never anchors the prior",
                 week, snap.get("snapshot_type"))
        return None
    return snap.get("anchor")


def poll_shift_vector(table: SeasonTable, anchor: dict[str, Any] | None) -> np.ndarray:
    """alpha-column location shift m_i aligned to table.housemates; 0.0 for
    housemates without a poll share. An all-zero vector reproduces the
    un-anchored spec exactly (gap-tolerant guarantee)."""
    m = np.zeros(table.N, dtype=float)
    if not anchor or not anchor.get("applied"):
        return m
    shifts = anchor.get("shifts", {})
    for i, name in enumerate(table.housemates):
        v = shifts.get(name)
        if isinstance(v, (int, float)):
            m[i] = float(v)
    LOG.info("poll anchor: %d/%d housemates anchored (kappa=%s, clip=%s, sources=%s)",
             int(np.count_nonzero(m)), table.N, anchor.get("kappa"),
             anchor.get("clip"), anchor.get("sources_used"))
    return m


def build_table(payload: dict[str, Any], housemates_cfg: list[dict[str, Any]],
                t_now: int | None = None, finale_week: int | None = None) -> SeasonTable:
    """daily_cpi payload + config roster -> SeasonTable. Pre-entry weeks and
    post-exit weeks simply have no record -> NaN (missing, never zero)."""
    names = [h["name"] for h in housemates_cfg]
    idx = {n: i for i, n in enumerate(names)}
    weeks_built = sorted(payload["weeks_built"])
    if not weeks_built:
        raise ValueError("no weeks built — nothing to model")
    t_now = t_now if t_now is not None else max(weeks_built)
    if t_now not in weeks_built:
        raise ValueError(f"snapshot week {t_now} has no data (built: {weeks_built})")

    with open(CONFIG_DIR / "season.json", encoding="utf-8") as fh:
        season_cfg = json.load(fh)
    if finale_week is None:
        # calendar-true: finale_week = ceil((finale_date - premiere_date)/7), fallback 10
        try:
            pre = date.fromisoformat(season_cfg["premiere_date"])
            fin = date.fromisoformat(season_cfg["finale_date"])
            finale_week = max(1, -(-(fin - pre).days // 7))
        except Exception:
            finale_week = 10
    twist_start = load_twist_start_week()
    twist_weekly = {int(w): int(w >= twist_start) for w in weeks_built}

    T, N = len(weeks_built), len(names)
    y = np.full((T, N), np.nan)
    sent = np.full((T, N), np.nan)
    at_risk = np.zeros((T, N), dtype=float)
    gambit = np.zeros((T, N), dtype=float)
    event = np.zeros((T, N), dtype=float)
    status_now: dict[str, str] = {}
    week_start: str | None = None

    for rec in payload["records"]:
        name, week = rec["housemate"], int(rec["week"])
        if name not in idx or week not in weeks_built:
            continue
        t = weeks_built.index(week)
        i = idx[name]
        y[t, i] = rec["cpi"] * COUNT_SCALE
        sent[t, i] = rec.get("sentiment", 0.0)
        at_risk[t, i] = float(rec.get("at_risk", 0))
        gambit[t, i] = float(rec.get("gambit_flag", 0))
        event[t, i] = 1.0 if rec.get("status", "active") != "active" else 0.0
        if week == t_now:
            status_now[name] = rec.get("status", "active")
            if week_start is None:
                week_start = rec.get("week_start")

    missing = [n for n in names if n not in status_now]
    if missing:
        LOG.warning("table: no t_now record for %s (treated as not in house)", missing)

    return SeasonTable(
        housemates=names, weeks_built=weeks_built, t_now=t_now, finale_week=finale_week,
        y=y, sent=sent, at_risk=at_risk, twist=np.array([twist_weekly[w] for w in weeks_built], float),
        gambit=gambit, event=event, status_now=status_now, season=int(payload.get("season", 0)),
        week_start=week_start,
        photos={h["name"]: h.get("photo", f"assets/photos/{h['name'].lower().replace(' ', '-')}.jpg")
                for h in housemates_cfg},
        missing_weeks=sorted(payload.get("missing_weeks", [])),
        backfilled_weeks=sorted({int(r["week"]) for r in payload["records"] if r.get("backfilled")}),
    )


# --------------------------------------------------------------------------- #
# Standardization (P5.1) — means/scales go into the run record
# --------------------------------------------------------------------------- #

def standardize(table: SeasonTable) -> dict[str, Any]:
    """Standardize t and sentiment; AtRisk/Twist stay binary (spec 3.1)."""
    t_raw = np.arange(1, table.T + 1, dtype=float)
    t_mean, t_scale = float(t_raw.mean()), float(t_raw.std())
    if t_scale == 0.0:
        t_scale = 1.0
    sent_flat = table.sent[~np.isnan(table.sent)]
    s_mean = float(sent_flat.mean()) if sent_flat.size else 0.0
    s_scale = float(sent_flat.std()) if sent_flat.size else 1.0
    if s_scale == 0.0:
        s_scale = 1.0
    sent_std = np.where(np.isnan(table.sent), 0.0, (table.sent - s_mean) / s_scale)
    LOG.info("standardization: t mean=%.4f scale=%.4f | sentiment mean=%.4f scale=%.4f",
             t_mean, t_scale, s_mean, s_scale)
    return {"t_mean": t_mean, "t_scale": t_scale, "t_std": (t_raw - t_mean) / t_scale,
            "sent_mean": s_mean, "sent_scale": s_scale, "sent_std": sent_std}


# --------------------------------------------------------------------------- #
# The joint model (P5.2–P5.4) + BMA candidate variants (P5.8)
# --------------------------------------------------------------------------- #

def build_model(table: SeasonTable, std: dict[str, Any], candidate: str = "baseline",
                poll_shift: np.ndarray | None = None) -> pm.Model:
    """Joint ZINB-count + Cox-survival model. `candidate` only changes priors on
    the beta_i scale (BMA); the count formula stays byte-for-byte in all three.
    `poll_shift` (length N) adds an alpha-column LOCATION shift only — the
    all-zero default is exactly the un-anchored spec."""
    if candidate not in BMA_CANDIDATES:
        raise ValueError(candidate)
    T, N, housemates = table.T, table.N, table.housemates
    with pm.Model(coords={"week": table.weeks_built, "housemate": housemates,
                          "effect": ["alpha", "beta"]}) as model:
        t_data = pm.Data("t_std", std["t_std"], dims="week")
        sent_data = pm.Data("sent_std", std["sent_std"], dims=("week", "housemate"))
        atrisk_data = pm.Data("at_risk", table.at_risk, dims=("week", "housemate"))
        twist_data = pm.Data("twist", table.twist, dims="week")

        # ---- priors: weakly-informative (spec 3.1), every value logged once ----
        alpha = pm.Normal("alpha", 0.0, 2.5)
        beta = pm.Normal("beta", 0.0, 2.5)
        gamma = pm.Normal("gamma", 0.0, 2.5)
        delta = pm.Normal("delta", 0.0, 2.5)
        theta = pm.Normal("theta", 0.0, 2.5)
        eta = pm.Normal("eta", 0.0, 2.5)
        # Correlated offsets, non-centered (2026-09-16 geometry fix): the
        # LKJCholeskyCov parameterization buries the beta-column scale inside
        # the Cholesky second row (rho*s_b, s_b*sqrt(1-rho^2)); near-zero
        # candidate scales funnel there and the correlation becomes
        # unidentified (probe: baseline 410 divergences, R-hat 1.62 -> 1.07
        # even at target_accept=0.99). At n=2, LKJ(2) on the correlation is
        # exactly rho = 2*Beta(2,2) - 1, so we sample (z_a, z_b, s_a, s_b,
        # rho) directly: same LKJ(2) x HalfNormal prior, no Cholesky-coupled
        # hyper-ridge, and the BMA candidate knob stays an interpretable scale.
        if candidate == "momentum":          # housemates diverge over time
            sd_beta_col = 2.0
        elif candidate == "baseline":        # housemates stay near the shared beta
            sd_beta_col = 0.5
        else:                                # heteroscedastic: post-Twist sigma^2_beta spike
            sd_beta_col = 1.0
        s_a = pm.HalfNormal("s_alpha", 1.0)
        s_b = pm.HalfNormal("s_beta", sd_beta_col)
        rho = 2.0 * pm.Beta("rho01", alpha=2.0, beta=2.0) - 1.0   # LKJ(2) at n=2
        za = pm.Normal("z_alpha", 0.0, 1.0, dims="housemate")
        zb = pm.Normal("z_beta", 0.0, 1.0, dims="housemate")
        # rho enters through the beta-column whitening: rho*za +
        # sqrt(1-rho^2)*zb keeps the implied pair-covariance at rho*s_a*s_b.
        # Poll-anchored prior (owner decision 2026-09-20): the poll share only
        # SHIFTS the alpha-column location (m_i, pre-centering); the scale, the
        # alpha/beta correlation, and the count formula below are untouched.
        # All-zero shift == un-anchored spec (gap-tolerant guarantee).
        poll_shift_d = pm.Data("poll_shift",
                               (np.zeros(N, dtype=float) if poll_shift is None
                                else np.asarray(poll_shift, dtype=float)),
                               dims="housemate")
        raw = pm.math.stack(
            [s_a * za + poll_shift_d,
             s_b * (rho * za + pm.math.sqrt(1.0 - rho**2) * zb)], axis=1)
        # Sum-to-zero centering: `alpha + alpha_i` / `beta + beta_i` have an
        # unidentified common-shift ridge (add c to every offset, subtract from
        # the population mean). The raw MvNormal leaves that direction in the
        # posterior and NUTS diverges on it (467 divs in the 4x2000 validation).
        # Centering removes the ridge; the count formula is unchanged after
        # substitution, and `offsets` remains the (housemate, effect) matrix
        # every downstream consumer reads.
        offsets = pm.Deterministic("offsets", raw - raw.mean(axis=0),
                                   dims=("housemate", "effect"))

        alpha_i, beta_i = offsets[:, 0], offsets[:, 1]
        LOG.info("priors[%s]: fixed effects Normal(0, 2.5); offsets non-centered, "
                 "s_alpha HalfNormal(1); s_beta HalfNormal(%s); rho = 2*Beta(2,2)-1 [LKJ(2) at n=2]",
                 candidate, sd_beta_col)

        # heteroscedastic candidate: beta_i scale spikes post-Twist (time-term only;
        # the frozen eta term keeps the plain beta_i per the count formula).
        # beta_i_w is always (week, housemate) so the time term stays 2-D.
        if candidate == "heteroscedastic":
            s_spike = pm.HalfNormal("s_spike", 1.0)
            beta_i_w = beta_i[None, :] * (1.0 + s_spike * twist_data[:, None])
        else:
            beta_i_w = beta_i[None, :] * pm.math.ones_like(twist_data[:, None])

        log_mu = (alpha + alpha_i[None, :]
                  + (beta + beta_i_w) * t_data[:, None]
                  + gamma * sent_data
                  + delta * atrisk_data
                  + theta * twist_data[:, None]
                  + eta * (twist_data[:, None] * beta_i[None, :]))
        mu = pm.Deterministic("mu", pm.math.exp(log_mu), dims=("week", "housemate"))

        psi = pm.Beta("psi", alpha=2.0, beta=2.0)
        nb_alpha = pm.HalfNormal("nb_alpha", 1.0)
        # ZINB likelihood as an explicit masked Potential (NOT a masked observed
        # RV): pymc 5.8's masked machinery injects IncSubtensor fill nodes that
        # trip a pytensor 2.15 optimizer assert under FAST_COMPILE, and the
        # explicit form is version-stable. Cells outside the house are masked
        # out of BOTH the potential and the stored pointwise log-likelihood
        # (exactly 0.0 there), so LOO compares candidates on common support.
        in_house_f = table.in_house().astype(float)
        y_obs = np.where(np.isnan(table.y), 0.0, table.y)
        obs_data = pm.Data("y_obs", y_obs, dims=("week", "housemate"))
        mask_data = pm.Data("y_mask", in_house_f, dims=("week", "housemate"))
        nb_dist = pm.NegativeBinomial.dist(mu=mu, alpha=nb_alpha)
        lp = pm.logp(nb_dist, obs_data)
        lp0 = pm.logp(nb_dist, 0.0)
        log_psi = pm.math.log(psi)
        log_1mpsi = pm.math.log(1.0 - psi)
        a0, b0 = log_psi, log_1mpsi + lp0
        m0 = pm.math.maximum(a0, b0)
        zinb_zero = m0 + pm.math.log(pm.math.exp(a0 - m0) + pm.math.exp(b0 - m0))
        y_ll = pm.math.where(obs_data > 0, log_1mpsi + lp, zinb_zero)
        y_ll_masked = y_ll * mask_data
        pm.Deterministic("y_loglik", y_ll_masked, dims=("week", "housemate"))
        pm.Potential("zinb_obs", y_ll_masked.sum())

        # ---- Cox partial likelihood (P5.4): frailty alpha_i is the ONLY shared
        # covariate (PLAN §4: "alpha_i shared as frailty"); baseline hazard is
        # eliminated by the weekly risk sets; relative hazards only.
        # Implemented with pure vector ops (dot + masked logsumexp) — fancy
        # indexing here makes the GRADIENT a scatter (IncSubtensor), which trips
        # a pytensor 2.15 optimizer assert (local_IncSubtensor_serialize).
        in_house = table.in_house()
        for t in range(T):
            events = table.event[t] > 0
            if not (events & in_house[t]).any():
                continue
            risk_vec = in_house[t].astype(float)             # (N,) 1 = in risk set
            event_vec = (events & in_house[t]).astype(float)  # (N,) 1 = event
            big_neg = -1.0e18
            lin_risk = pm.math.switch(risk_vec > 0, alpha_i, big_neg)
            pm.Potential(f"cox_week_{t}",
                         pm.math.dot(event_vec, alpha_i)
                         - event_vec.sum() * pm.math.logsumexp(lin_risk))
        LOG.info("model[%s]: N=%d T=%d weeks, cox events at weeks %s", candidate, N, T,
                 [int(w) for w in np.array(table.weeks_built)[table.event.sum(axis=1) > 0]])
    return model


# --------------------------------------------------------------------------- #
# Sampling + gates (P5.9)
# --------------------------------------------------------------------------- #

def sample_model(model: pm.Model, draws: int, tune: int, chains: int, seed: int,
                 lite: bool) -> az.InferenceData:
    """4 chains x 2000 draws full spec (lite: reduced, still labelled upstream).

    Sequential sampling is the default: on Windows, pymc's spawned workers
    re-import __main__, which under pytest re-collects the whole suite in each
    child (recursive collection -> hang). Parallel chains stay available via
    BBN_MCMC_CORES for the Saturday run on machines where spawn is safe.
    """
    cores = int(os.environ.get("BBN_MCMC_CORES", "1"))
    # Geometry dial (divergence mitigation): default 0.9; raise to 0.95-0.99 via
    # BBN_TARGET_ACCEPT when probes show divergences (runbook: cheapest fix first).
    target_accept = float(os.environ.get("BBN_TARGET_ACCEPT", "0.9"))
    with model:
        idata = pm.sample(draws=draws, tune=tune, chains=chains,
                          cores=max(1, min(cores, chains)), random_seed=seed,
                          target_accept=target_accept, progressbar=False,
                          compute_convergence_checks=True)
    div = int(idata.sample_stats["diverging"].values.sum())
    LOG.info("sampled: %d draws x %d chains seed=%d divergences=%d lite=%s",
             draws, chains, seed, div, lite)
    return idata


def extract_draws(post: az.data.inference_data.Dataset) -> dict[str, np.ndarray]:
    """Flatten (chain, draw) -> draw vectors/matrices from the posterior group."""
    off = post["offsets"].values.reshape(-1, post.sizes["housemate"], 2)
    return {
        "alpha": post["alpha"].values.reshape(-1),
        "beta": post["beta"].values.reshape(-1),
        "gamma": post["gamma"].values.reshape(-1),
        "delta": post["delta"].values.reshape(-1),
        "theta": post["theta"].values.reshape(-1),
        "eta": post["eta"].values.reshape(-1),
        "alpha_i": off[..., 0],
        "beta_i": off[..., 1],
    }


def rhat_max(idata: az.InferenceData) -> float:
    """Max rank-normalised R-hat over all posterior variables.

    NaN on single-chain runs (R-hat is undefined there) — `convergence_gate`
    treats 1 chain as a smoke-run exemption, never a silent pass.

    Structural constants are excluded: e.g. the LKJ Cholesky correlation's
    diagonal is 1.0 by construction, so its R-hat is 0/0 = NaN (arviz divides
    zero between-variance by zero within-variance). NaN there is NOT a
    pathology — a genuinely stuck chain yields huge/inf R-hat, which the gate
    still rejects. This is what crashed the 2026-09-16 validation (2.6 h of
    healthy draws lost to `np.max` propagating one structural NaN).
    """
    rh = az.rhat(idata, method="rank")
    finite: list[float] = []
    n_struct = 0
    for v in rh.data_vars:
        arr = np.asarray(rh[v], dtype=float).ravel()
        n_struct += int(np.isnan(arr).sum())
        finite.extend(arr[np.isfinite(arr)].tolist())
    if n_struct:
        LOG.info("rhat: %d structural-constant coordinate(s) excluded (e.g. LKJ corr diagonal)",
                 n_struct)
    return float(np.max(finite)) if finite else float("nan")


def convergence_gate(idata: az.InferenceData, gate: float = RHAT_GATE) -> tuple[float, bool]:
    """P5.9 gate: R-hat < 1.01 else reject (caller keeps last good file).

    Runs with a single chain skip the gate (R-hat is undefined) and are
    labelled as such — production Saturday runs always sample 4 chains.
    """
    n_chains = idata.posterior.sizes["chain"]
    if n_chains < 2:
        LOG.warning("R-hat gate: skipped (single chain) - smoke run, not labeled as production")
        return float("nan"), True
    rmax = rhat_max(idata)
    ok = rmax < gate
    (LOG.info if ok else LOG.error)("R-hat gate: max=%.4f gate=%.2f -> %s",
                                    rmax, gate, "PASS" if ok else "REJECT")
    if not ok:
        # Diagnostics: name the worst coordinates so the geometry fix is targeted,
        # not guessed (2026-09-16 decision: log-on-failure only, not per-run).
        rh = az.rhat(idata, method="rank")
        flat = [(float(np.nanmax(np.asarray(rh[v], dtype=float))), v) for v in rh.data_vars]
        # Structural constants (NaN R-hat, e.g. LKJ corr diagonal) excluded —
        # see rhat_max(). Sort descending over finite values only.
        flat = [(r, v) for r, v in flat if np.isfinite(r)]
        flat.sort(key=lambda t: -t[0])
        LOG.error("gate diagnostics - worst variables: %s",
                  [(v, round(r, 4)) for r, v in flat[:5]])
        worst_var = flat[0][1]
        arr = np.asarray(rh[worst_var])
        if arr.ndim >= 1:
            for idx in np.argsort(arr.ravel())[-3:][::-1]:
                coords = np.unravel_index(idx, arr.shape)
                labels = [f"{d}={rh[worst_var].coords[d].values[c]}"
                          for d, c in zip(rh[worst_var].dims, coords)]
                LOG.error("  %s: R-hat=%.4f [%s]",
                          worst_var, arr.ravel()[idx], ", ".join(labels))
    return rmax, ok


# --------------------------------------------------------------------------- #
# Gambit filter (frozen, byte-for-byte) + win probabilities
# --------------------------------------------------------------------------- #

def log_mu_at(draws: dict[str, np.ndarray], t_std_value: float, sent_row: np.ndarray,
              atrisk_row: np.ndarray, twist_value: float,
              spike: float = 0.0) -> np.ndarray:
    """Frozen count formula evaluated at one week for every draw: (D, N).
    `spike` (heteroscedastic BMA candidate only) rescales the beta_i time-term
    post-Twist, mirroring the model-side beta_i_eff."""
    lin = (draws["alpha"][:, None] + draws["alpha_i"]
           + (draws["beta"][:, None] + draws["beta_i"]) * t_std_value
           + draws["gamma"][:, None] * sent_row[None, :]
           + draws["delta"][:, None] * atrisk_row[None, :]
           + draws["theta"][:, None] * twist_value
           + draws["eta"][:, None] * twist_value * draws["beta_i"])
    if spike:
        lin = lin + draws["beta_i"] * spike * twist_value * t_std_value
    return lin


def gambit_filter(mu: np.ndarray, gambit_flag: np.ndarray) -> np.ndarray:
    """Frozen eligibility filter, posterior-predictive form.

    WinProb_i = 0.0 if GambitFlag_i == 1 else exp(mu_i)/sum_{j not in Gambit} exp(mu_j)

    `mu` (..., N) raw linear predictor; `gambit_flag` (N,) 0/1 for the snapshot.
    Zeroed exactly — never down-weighted."""
    gambit_flag = np.asarray(gambit_flag, dtype=bool)
    if gambit_flag.all():
        raise ValueError("gambit filter: every housemate is prize-ineligible — "
                         "no winner exists; refusing to normalise")
    masked = np.where(gambit_flag, -np.inf, mu)
    masked = masked - np.max(masked, axis=-1, keepdims=True)
    w = np.exp(masked)
    w = np.where(gambit_flag, 0.0, w)          # exact 0.0 for Gambit housemates
    total = w.sum(axis=-1, keepdims=True)
    return np.where(total > 0, w / np.where(total > 0, total, 1.0), 0.0)


# --------------------------------------------------------------------------- #
# Dirichlet-Multinomial posterior predictive + rank machinery (P5.6)
# --------------------------------------------------------------------------- #

def dm_win_shares(mu: np.ndarray, gambit_flag: np.ndarray, rng: np.random.Generator,
                  n_draws: int = N_DM_DRAWS) -> np.ndarray:
    """10k Dirichlet-Multinomial draws of the win share, filter applied first."""
    w = gambit_filter(mu, gambit_flag)                     # (D, A)
    if w.shape[1] == 1:                                    # last-housemate edge case
        return np.ones((n_draws, 1))
    shares = np.empty((n_draws, w.shape[1]))
    for d in range(n_draws):
        row = w[d % len(w)]
        if row.sum() > 0:
            # underflowed cells are exactly 0 -> Gamma(0) is invalid; an epsilon
            # keeps them at ~0 probability without blowing up the draw
            alpha = np.where(DM_CONCENTRATION * row > 0, DM_CONCENTRATION * row, 1e-12)
            p = rng.dirichlet(alpha)
        else:
            p = row
        # Pass the FULL probability vector: numpy's multinomial treats the last
        # PASSED pval as the remainder bin, so p[:-1] silently folded the last
        # housemate's mass into the second-to-last column (the week-8 bug that
        # hard-zeroed Yusuf's snapshot while inflating everyone else slightly).
        # With the full vector, numpy handles the final category internally and
        # the drift-shave hack is unnecessary.
        p = p / p.sum()
        votes = rng.multinomial(NOMINAL_VOTES, p)
        shares[d] = votes / NOMINAL_VOTES
    return shares


def rank_draws(shares: np.ndarray, names: list[str]) -> np.ndarray:
    """Per-draw ranks (0 = best) with deterministic alphabetical tie-break."""
    alpha_order = np.argsort(names)                        # alphabetical column order
    p = shares[:, alpha_order]
    rows = np.arange(p.shape[0])[:, None]
    ranks_alpha = np.empty_like(p, dtype=int)
    order = np.argsort(-p, axis=1, kind="stable")          # ties -> alphabetical
    ranks_alpha[rows, order] = np.arange(p.shape[1])[None, :]
    ranks = np.empty_like(ranks_alpha)
    ranks[:, alpha_order] = ranks_alpha
    return ranks


def rank_products(shares: np.ndarray, names: list[str]) -> dict[str, Any]:
    """p_rank_1 / p_top3 / p_top5 + podium slot probabilities (P5.6, D9, D12)."""
    ranks = rank_draws(shares, names)
    n_active = shares.shape[1]
    out: dict[str, Any] = {}
    for i, name in enumerate(names):
        col = ranks[:, i]
        out[name] = {
            "p_rank_1": float((col == 0).mean()),
            "p_top3": float((col <= 2).mean()),
            "p_top5": float((col <= min(4, n_active - 1)).mean()),
        }
    return {"per_housemate": out, "ranks": ranks}


def podium_from_ranks(ranks: np.ndarray, names: list[str]) -> dict[str, Any]:
    """Podium slots with slot probabilities; assigned without replacement (one
    occupant per slot), exact ties -> alphabetical."""
    taken: set[int] = set()

    def slot(k: int) -> dict[str, Any]:
        probs = (ranks == k).mean(axis=0)
        for i in sorted(range(len(names)), key=lambda i: (-probs[i], names[i])):
            if i not in taken:
                taken.add(i)
                return {"name": names[i], "prob": float(probs[i])}
        raise AssertionError("more slots than names")

    return {"winner": slot(0), "runner_up": slot(1), "second_runner_up": slot(2)}


def statistical_ties(shares: np.ndarray, names: list[str]) -> dict[str, list[str]]:
    """Adjacent rows (by median share) whose 89% HDIs overlap -> tie marker."""
    out: dict[str, list[str]] = {n: [] for n in names}
    med = np.median(shares, axis=0)
    hdis = [az.hdi(shares[:, i], hdi_prob=HDI_PROB) for i in range(len(names))]
    order = sorted(range(len(names)), key=lambda i: (-med[i], names[i]))
    for a, b in zip(order[:-1], order[1:]):
        if max(hdis[a][0], hdis[b][0]) <= min(hdis[a][1], hdis[b][1]):
            out[names[a]].append(names[b])
            out[names[b]].append(names[a])
    return out


# --------------------------------------------------------------------------- #
# Trend projection (P5.7) — secondary readout, never merged (D14)
# --------------------------------------------------------------------------- #

def trend_podium(draws: dict[str, np.ndarray], std: dict[str, Any], table: SeasonTable,
                 active: np.ndarray, gambit_now: np.ndarray, rng: np.random.Generator
                 ) -> dict[str, Any]:
    """beta_i momentum extrapolation to the finale with horizon-scaled uncertainty
    (posterior NB residual CV x sqrt(horizon weeks) — spec open question #1 default).
    All matrices are already sliced to ACTIVE housemates (columns aligned)."""
    t_fin_std = float((table.finale_week - std["t_mean"]) / std["t_scale"])
    twist_last = float(table.twist[-1])
    # at the finale: t moves; sentiment/at-risk unknown -> means (0); twist persists
    lin_fin = (draws["alpha"][:, None] + draws["alpha_i"][:, active]
               + (draws["beta"][:, None] + draws["beta_i"][:, active]) * t_fin_std
               + draws["theta"][:, None] * twist_last
               + draws["eta"][:, None] * twist_last * draws["beta_i"][:, active])
    # residual scale: per-draw NB sd / mean at t_now, median across draws (log CV)
    lin_now = (draws["alpha"][:, None] + draws["alpha_i"][:, active]
               + (draws["beta"][:, None] + draws["beta_i"][:, active]) * float(std["t_std"][-1])
               + draws["gamma"][:, None] * std["sent_std"][-1][active][None, :]
               + draws["delta"][:, None] * table.at_risk[-1][active][None, :]
               + draws["theta"][:, None] * twist_last
               + draws["eta"][:, None] * twist_last * draws["beta_i"][:, active])
    mu_now = np.exp(lin_now)
    nb_a = np.clip(draws.get("nb_alpha", np.full(mu_now.shape[0], 2.0))[:, None], 0.1, None)
    var_now = mu_now + mu_now ** 2 / nb_a
    sigma_week = float(np.median(np.sqrt(var_now).mean(axis=1) / mu_now.mean(axis=1)))
    horizon = max(table.finale_week - table.t_now, 1)
    noise = rng.normal(0.0, sigma_week * np.sqrt(horizon), size=lin_fin.shape)
    shares = gambit_filter(lin_fin + noise, gambit_now)
    names_active = [table.housemates[i] for i in active]
    ranks = rank_draws(shares, names_active)
    podium = podium_from_ranks(ranks, names_active)
    return {
        "method": "beta_i momentum extrapolation to finale",
        "uncertainty": f"posterior NB residual CV x sqrt(horizon); sigma_week={sigma_week:.4f}",
        "horizon_week": table.finale_week,
        "podium": [podium["winner"]["name"], podium["runner_up"]["name"],
                   podium["second_runner_up"]["name"]],
    }


# --------------------------------------------------------------------------- #
# At-risk panel (D10) — relative Cox hazards, nominated-only
# --------------------------------------------------------------------------- #

def at_risk_panel(draws: dict[str, np.ndarray], std: dict[str, Any], table: SeasonTable,
                  active: np.ndarray) -> list[dict[str, Any]]:
    """Nominated (at_risk==1 at t_now) ACTIVE housemates ranked by posterior
    relative hazard (median over draws; 1.0 = average housemate that week)."""
    sent_row = std["sent_std"][-1]
    atrisk_row = table.at_risk[-1]
    twist_v = float(table.twist[-1])
    haz = (draws["alpha_i"]
           + draws["gamma"][:, None] * sent_row[None, :]
           + draws["delta"][:, None] * atrisk_row[None, :]
           + draws["theta"][:, None] * twist_v
           + draws["eta"][:, None] * twist_v * draws["beta_i"])
    rel = np.exp(haz - haz.mean(axis=1, keepdims=True))    # relative to the average
    median_rel = np.median(rel, axis=0)
    rows = []
    for i in active:
        if atrisk_row[i] > 0:
            rows.append({"name": table.housemates[i], "relative_hazard": float(median_rel[i]),
                         "nominated": True})
    rows.sort(key=lambda r: (-r["relative_hazard"], r["name"]))
    return rows


# --------------------------------------------------------------------------- #
# Prior predictive sanity (P5.10 / spec 8.2)
# --------------------------------------------------------------------------- #

def prior_predictive_check(model: pm.Model, table: SeasonTable, n: int = 200,
                           seed: int = MASTER_SEED + 700) -> dict[str, Any]:
    """Plausible season shapes: no 0%/100% win-share pathologies, sane counts."""
    with model:
        prior = pm.sample_prior_predictive(samples=n, random_seed=seed,
                                           return_inferencedata=False)
    off = prior["offsets"]  # (n, N, 2)
    d = {"alpha": prior["alpha"], "beta": prior["beta"], "gamma": prior["gamma"],
         "delta": prior["delta"], "theta": prior["theta"], "eta": prior["eta"],
         "alpha_i": off[..., 0], "beta_i": off[..., 1]}
    std = standardize(table)
    lin = log_mu_at(d, float(std["t_std"][-1]), std["sent_std"][-1],
                    table.at_risk[-1], float(table.twist[-1]))
    shares = gambit_filter(lin, table.gambit[-1])
    # simulate the prior predictive of y (ZINB) at t_now for the count sanity check
    mu_prior = np.exp(lin)                                   # (n, N)
    psi_p = np.asarray(prior["psi"])[:, None]
    a_p = np.asarray(prior["nb_alpha"])[:, None]
    rng = np.random.default_rng(seed + 1)
    y_sim = rng.negative_binomial(a_p, a_p / (a_p + mu_prior)) \
        * (rng.random(mu_prior.shape) >= psi_p)
    y_med = float(np.median(y_sim))
    # Pathology = an EXACT 0%/100% win share for a PRIZE-ELIGIBLE housemate
    # (degenerate normalisation) — wide-prior tail draws (e.g. 99.9%) are legal
    # and reported, not failed. Gambit-flagged columns are legitimately exactly 0
    # by the frozen filter, so they are excluded from the lower-bound check.
    elig = ~np.asarray(table.gambit[-1], dtype=bool)
    upper_ok = (shares < 1.0 - 1e-6).all() if elig.sum() >= 2 else True
    # (a lone eligible housemate holds share == 1.0 by arithmetic, not pathology)
    ok = bool(np.all(shares[:, elig] > 0.0) and upper_ok
              and np.all(np.isfinite(lin)) and 0.0 <= y_med < 100 * COUNT_SCALE)
    LOG.info("prior predictive: eligible shares in [%.2e, %.4f], y median=%.1f -> %s",
             float(shares[:, elig].min()), float(shares.max()), y_med,
             "PASS" if ok else "FAIL")
    return {"pass": ok, "share_min_eligible": float(shares[:, elig].min()),
            "share_max": float(shares.max()), "y_median": y_med, "n": n, "seed": seed}


# --------------------------------------------------------------------------- #
# Full product assembly (P5.6/P5.7/P5.8 + spec 3.3) — BMA pooled
# --------------------------------------------------------------------------- #

def _loo_pointwise(idata: az.InferenceData) -> np.ndarray:
    """Pointwise LOO ELPD via ArviZ, from the model's stored pointwise ZINB
    log-likelihood (`y_loglik`, recorded as a deterministic). Masked (not in
    house) cells are exactly 0.0 in every candidate — the identical mask keeps
    cross-candidate comparisons on common support."""
    yll = np.asarray(idata.posterior["y_loglik"], dtype=float)   # (chain, draw, T, N)
    yll = yll.reshape(yll.shape[0], yll.shape[1], -1)            # (chain, draw, P)
    # az.loo needs both a posterior and a log_likelihood group; wrap the array
    # explicitly (dummy posterior of matching shape) to stay version-stable.
    wrapped = az.from_dict(posterior={"w": yll}, log_likelihood={"y": yll})
    res = az.loo(wrapped, var_name="y", pointwise=True)
    loo_i = getattr(res, "loo_i", None)
    if loo_i is None:                       # newer arviz renamed loo_i -> elpd_i
        loo_i = res["elpd_i"]
    return np.asarray(loo_i, float).ravel()


def _pseudo_bma_plus(elpd: dict[str, np.ndarray], b: int = 1000,
                     seed: int = MASTER_SEED + 600) -> dict[str, float]:
    """Bayesian-bootstrap Pseudo-BMA+ over the common pointwise support
    (same estimator family as az.compare(method='BB-pseudo-BMA'), made explicit
    so masked cells stay excluded and the seed controls everything)."""
    names = sorted(elpd)
    e = np.vstack([elpd[k] for k in names])               # (C, P)
    rng = np.random.default_rng(seed)
    w_b = rng.dirichlet(np.ones(e.shape[1]), size=b)      # (B, P) simplex weights
    scores = w_b @ e.T                                    # (B, C)
    scores = scores - scores.max(axis=1, keepdims=True)
    wb = np.exp(scores)
    wb = wb / wb.sum(axis=1, keepdims=True)
    w = wb.mean(axis=0)
    return {k: float(v) for k, v in zip(names, w)}


def bma_weights(idatas: dict[str, az.InferenceData], gate: float = RHAT_GATE,
                seed: int = MASTER_SEED + 600) -> dict[str, float]:
    """Pseudo-BMA+ weights via ArviZ LOO ELPD with bootstrapping.
    Candidates failing the R-hat gate get weight 0. Fallback: equal weights."""
    keep = {k: ida for k, ida in idatas.items() if convergence_gate(ida, gate)[1]}
    dropped = set(idatas) - set(keep)
    if dropped:
        LOG.warning("BMA: candidates %s failed the R-hat gate -> weight 0", sorted(dropped))
    if len(keep) < 2:
        # exactly one survivor -> it takes everything; none survive -> all zero
        # (the runner's own gate raises ModelRejected before assembly happens)
        w = {k: (1.0 if k in keep else 0.0) for k in idatas}
        LOG.info("BMA: degenerate field -> weights %s", w)
        return w
    try:
        pointwise = {k: _loo_pointwise(idatas[k]) for k in keep}
        w = _pseudo_bma_plus(pointwise, seed=seed)
        n_cells = len(next(iter(pointwise.values())))
        LOG.info("BMA BB-pseudo-BMA+ weights (P=%d cells): %s", n_cells,
                 {k: round(v, 4) for k, v in w.items()})
    except Exception as exc:  # arviz drift / pathological LOO -> honest fallback
        LOG.warning("BMA compare failed (%s); falling back to equal weights", exc)
        w = {k: 1.0 / len(keep) if k in keep else 0.0 for k in idatas}
    w = {k: w.get(k, 0.0) for k in idatas}
    s = sum(w.values()) or 1.0
    return {k: v / s for k, v in w.items()}


def _pool(allocation: dict[str, int], matrices: dict[str, np.ndarray],
          seed: int) -> np.ndarray:
    """Mixture sample: draw rows from each candidate's matrix per allocation."""
    rng = np.random.default_rng(seed)
    parts = []
    for cand, n in allocation.items():
        m = matrices[cand]
        idx = rng.integers(0, m.shape[0], size=n)
        parts.append(m[idx])
    return np.concatenate(parts, axis=0)


def assemble_products(idatas: dict[str, az.InferenceData], weights: dict[str, float],
                      table: SeasonTable, std: dict[str, Any], lite: bool,
                      seed: int = MASTER_SEED) -> dict[str, Any]:
    """All weekly-standings products from the existing posterior draws."""
    return assemble_from_draws(idatas, weights, table, std, lite, seed=seed)


def assemble_from_draws(idatas: dict[str, az.InferenceData], weights: dict[str, float],
                        table: SeasonTable, std: dict[str, Any], lite: bool,
                        seed: int = MASTER_SEED) -> dict[str, Any]:
    """Draw-consuming core of the weekly-standings products.

    Consumes posterior-like InferenceData objects (real MCMC runs from
    `run_inference`, or prior-predictive InferenceData from
    `run_prior_placeholder`) so every downstream product (DM shares, ranks,
    podium, history, trend, at-risk) is exercised identically for both.
    """
    # gate-failed candidates carry weight 0 — exclude them from every pool
    idatas = {k: v for k, v in idatas.items() if weights.get(k, 0.0) > 0.0}
    if not idatas:
        raise ValueError("no candidates survived the R-hat gate; refusing to assemble")
    anchor = max(idatas, key=lambda k: weights.get(k, 0.0))   # trend/at-risk candidate
    LOG.info("assembling products from %s (anchor for trend/at-risk: %s)",
             sorted(idatas), anchor)
    t_now_std = float(std["t_std"][-1])
    active = table.active_idx()
    names_active = [table.housemates[i] for i in active]
    gambit_now = table.gambit[-1][active]

    # per-candidate matrices, pooled by BMA weights into exactly N_DM_DRAWS rows
    alloc_raw = {k: N_DM_DRAWS * weights.get(k, 0.0) for k in idatas}
    allocation = {k: int(round(v)) for k, v in alloc_raw.items()}
    while sum(allocation.values()) != N_DM_DRAWS:          # rounding fix, deterministic
        k = max(allocation, key=lambda k: alloc_raw[k] - allocation[k])
        allocation[k] += 1 if sum(allocation.values()) < N_DM_DRAWS else -1

    snap_mu, week_mu, fin_rng_draws = {}, {}, {}
    for cand, idata in idatas.items():
        d = extract_draws(idata.posterior)
        d["nb_alpha"] = np.asarray(idata.posterior["nb_alpha"]).reshape(-1)
        spike = (float(np.median(np.asarray(idata.posterior["s_spike"]).reshape(-1)))
                 if cand == "heteroscedastic" else 0.0)
        snap_mu[cand] = log_mu_at(d, t_now_std, std["sent_std"][-1],
                                  table.at_risk[-1], float(table.twist[-1]), spike)
        # weekly history: per-week snapshot shares for every in-house housemate
        week_mu[cand] = []
        for t in range(table.T):
            lm = log_mu_at(d, float(std["t_std"][t]), std["sent_std"][t],
                           table.at_risk[t], float(table.twist[t]), spike)
            inhouse = table.in_house()[t]
            flags = table.gambit[t]
            share = np.zeros((lm.shape[0], table.N))
            if inhouse.any():
                cols = np.flatnonzero(inhouse)
                share[:, cols] = gambit_filter(lm[:, cols], flags[cols])
            week_mu[cand].append(share)
        fin_rng_draws[cand] = d

    pooled_snap = _pool(allocation, snap_mu, seed + 100)
    pooled_shares = dm_win_shares(pooled_snap[:, active], gambit_now,
                                  np.random.default_rng(seed + 200))
    ranked = rank_products(pooled_shares, names_active)
    ranks = ranked["ranks"]

    per_hm: dict[str, dict[str, Any]] = {}
    ties = statistical_ties(pooled_shares, names_active)
    # pairwise P(i finishes above j) from the pooled DM shares — spec: below-chart
    # pairwise panel (win-prob difference for any two picks + likely winner)
    pairwise: dict[str, dict[str, float]] = {}
    for a_i, a in enumerate(names_active):
        pairwise[a] = {b: float((pooled_shares[:, a_i] > pooled_shares[:, b_i]).mean())
                       for b_i, b in enumerate(names_active) if b != a}
    for i, name in enumerate(names_active):
        col = pooled_shares[:, i]
        hdi = az.hdi(col, hdi_prob=HDI_PROB)
        per_hm[name] = {
            "win_prob_median": float(np.median(col)), "hdi_89": [float(hdi[0]), float(hdi[1])],
            "p_rank_1": ranked["per_housemate"][name]["p_rank_1"],
            "p_top3": ranked["per_housemate"][name]["p_top3"],
            "p_top5": ranked["per_housemate"][name]["p_top5"],
            "statistical_tie_with": sorted(ties.get(name, [])),
        }

    # history (pooled mixture, per week, in-house housemates only)
    pooled_week = {t: _pool(allocation, {c: week_mu[c][t] for c in idatas}, seed + 300 + t)
                   for t in range(table.T)}
    history: dict[str, list[dict[str, Any]]] = {n: [] for n in table.housemates}
    for t, week in enumerate(table.weeks_built):
        for i in range(table.N):
            if not table.in_house()[t, i]:
                continue
            col = pooled_week[t][:, i]
            hdi = az.hdi(col, hdi_prob=HDI_PROB)
            history[table.housemates[i]].append(
                {"week": int(week), "median": float(np.median(col)),
                 "hdi_89": [float(hdi[0]), float(hdi[1])]})

    # trend projection + at-risk panel from the anchor candidate, own seed
    trend = trend_podium(fin_rng_draws[anchor], std, table, active, gambit_now,
                         np.random.default_rng(seed + 400))

    housemates_out = []
    for i, name in enumerate(table.housemates):
        # No t_now record == not in the house (same convention as active_idx):
        # label from the event row — mid-week DQs/walkouts are coded as
        # evictions (weekly-standings spec 4.2).
        status = table.status_now.get(name)
        if status is None:
            status = "evicted" if (table.event[:, i] > 0).any() else "inactive"
        cur = per_hm.get(name)
        if status != "active" or cur is None:
            cur = cur or {"win_prob_median": 0.0, "hdi_89": [0.0, 0.0],
                          "p_rank_1": 0.0, "p_top3": 0.0, "p_top5": 0.0,
                          "statistical_tie_with": []}
        housemates_out.append({
            "name": name, "photo": table.photos.get(name,
                                                    f"assets/photos/{name.lower().replace(' ', '-')}.jpg"),
            "status": status,
            "evicted_week": next((int(table.weeks_built[t]) for t in range(table.T)
                                  if table.event[t, i] > 0), None),
            "final_place": None,  # ground truth only after the finale Sunday
            "gambit_flag": int(table.gambit[-1, i]),
            **cur,
            "history": history.get(name, []),
        })

    return {
        "podium": podium_from_ranks(ranks, names_active),
        "pairwise": pairwise,
        "precision": "lite" if lite else "full",   # never silent (P5.9)
        "trend_projection": trend,                 # secondary — never merged (D14)
        "at_risk": at_risk_panel(fin_rng_draws[anchor], std, table, active),
        "housemates": housemates_out,
        "model_weights": {k: round(float(weights.get(k, 0.0)), 4) for k in BMA_CANDIDATES},
        "diagnostics": {
            "dm_draws": N_DM_DRAWS, "dm_concentration": DM_CONCENTRATION,
            "nominal_votes": NOMINAL_VOTES, "seed": seed, "trend_seed": seed + 400,
            "hdi_prob": HDI_PROB, "active_count": int(len(active)),
        },
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run_inference(payload: dict[str, Any], housemates_cfg: list[dict[str, Any]],
                  lite: bool = False, full: bool = False, t_now: int | None = None,
                  seed: int = MASTER_SEED, prior_check: bool = False,
                  draws_override: int | None = None,
                  chains_override: int | None = None,
                  candidates_override: list[str] | None = None,
                  checkpoint_dir: str | None = None,
                  tune_override: int | None = None) -> dict[str, Any]:
    """Table -> 3 candidate models -> gates -> BMA -> standings products."""
    started = time.time()
    table = build_table(payload, housemates_cfg, t_now=t_now)
    std = standardize(table)
    poll_anchor = load_poll_anchor(table.t_now)
    poll_shift = poll_shift_vector(table, poll_anchor)
    if lite:
        draws, tune, chains = 500, 500, 2
    elif full:
        draws, tune, chains = 2000, 1000, 4
    else:
        draws, tune, chains = 1000, 1000, 4

    idatas: dict[str, az.InferenceData] = {}
    rhats: dict[str, float] = {}
    draws_eff = draws_override if draws_override is not None else draws
    chains_eff = chains_override if chains_override is not None else chains
    tune_eff = tune_override if tune_override is not None else tune
    candidates_eff = candidates_override or BMA_CANDIDATES
    for k, cand in enumerate(candidates_eff):
        cpath = (Path(checkpoint_dir) / f"idata_{cand}.nc") if checkpoint_dir else None
        if cpath and cpath.exists():  # A4 insurance: resume after a crash/kill
            LOG.info("resume: loading checkpoint %s", cpath)
            idatas[cand] = az.from_netcdf(cpath)
            rhats[cand] = rhat_max(idatas[cand])
            continue
        model = build_model(table, std, candidate=cand, poll_shift=poll_shift)
        if prior_check:
            prior_predictive_check(model, table, seed=seed + 700 + k)
        idatas[cand] = sample_model(model, draws_eff, tune_eff, chains_eff, seed + k, lite)
        rhats[cand] = rhat_max(idatas[cand])
        if cpath:  # save before the next stage — sampling is never thrown away
            cpath.parent.mkdir(parents=True, exist_ok=True)
            az.to_netcdf(idatas[cand], cpath)
            LOG.info("checkpoint: %s", cpath)
        del model

    gate_cand = "baseline" if "baseline" in idatas else next(iter(idatas))
    rhat_head, ok = convergence_gate(idatas[gate_cand])
    if not ok:  # reject BEFORE BMA/assembly — caller keeps the last good file
        raise ModelRejected(f"R-hat {rhat_head:.4f} >= {RHAT_GATE} on '{gate_cand}' — "
                            "run rejected; keep last good predictions.json and flag staleness")
    weights = bma_weights(idatas, seed=seed + 600)
    products = assemble_products(idatas, weights, table, std, lite, seed=seed)
    products["rhat_max"] = round(rhat_head, 5)
    products["rhat_by_candidate"] = {k: round(v, 5) for k, v in rhats.items()}
    # Divergence bookkeeping per the 2026-09-16 gate decision: headline candidate
    # must sample 0 divergences; non-headline residue is tolerated, logged, and
    # carries BMA weight consequences via the R-hat gate only.
    products["divergences_by_candidate"] = {
        k: int(ida.sample_stats["diverging"].values.sum()) for k, ida in idatas.items()}
    products["priors"] = dict(PRIORS)
    if poll_anchor is not None:
        products["priors"]["poll_anchor"] = {
            "applied": bool(poll_anchor.get("applied")),
            "kappa": poll_anchor.get("kappa"), "clip": poll_anchor.get("clip"),
            "sources_used": poll_anchor.get("sources_used", []),
            "shifts": poll_anchor.get("shifts", {}),
        }
    products["polls"] = {
        "week": table.t_now,
        "anchor_applied": bool(poll_anchor.get("applied")) if poll_anchor else False,
        "anchor": poll_anchor,
    }
    products["standardization"] = {k: v for k, v in std.items()
                                   if k in ("t_mean", "t_scale", "sent_mean", "sent_scale")}
    products["run_seconds"] = round(time.time() - started, 1)
    products["generated_at"] = datetime.now(timezone.utc).isoformat()
    LOG.info("run_inference done in %.1fs (gate PASS, rhat_max=%.4f)",
             products["run_seconds"], rhat_head)
    return products


def run_prior_placeholder(payload: dict[str, Any], housemates_cfg: list[dict[str, Any]],
                          seed: int = MASTER_SEED, n_samples: int = 1000,
                          t_now: int | None = None) -> dict[str, Any]:
    """No-sampling placeholder products for UI/deploy work (P7/P8 unblocking).

    Draws from the PRIOR predictive of the baseline candidate (plausible season
    shapes by design, zero data information) and pushes those draws through the
    exact same downstream machinery as a real run. The product is labelled
    precision="prior-predictive" and carries placeholder=True so no consumer
    can mistake it for inference. NOT for publication as predictions.
    """
    started = time.time()
    table = build_table(payload, housemates_cfg, t_now=t_now)
    std = standardize(table)
    model = build_model(table, std, candidate="baseline")
    with model:
        prior = pm.sample_prior_predictive(samples=n_samples, random_seed=seed,
                                           return_inferencedata=True)
    idata = az.from_dict(posterior={k: np.asarray(v) for k, v in prior.prior.items()},
                         coords={"week": table.weeks_built, "housemate": table.housemates,
                                 "effect": ["alpha", "beta"]},
                         dims={"offsets": ["housemate", "effect"],
                               "t_std": ["week"], "sent_std": ["week", "housemate"],
                               "at_risk": ["week", "housemate"], "twist": ["week"]})
    products = assemble_from_draws({"prior": idata}, {"prior": 1.0}, table, std,
                                   lite=False, seed=seed)
    products["precision"] = "prior-predictive"      # never silent (P5.9 analogue)
    products["placeholder"] = True
    products["rhat_max"] = None
    products["rhat_by_candidate"] = {}
    products["model_weights"] = {"prior": 1.0}
    products["priors"] = dict(PRIORS)
    products["standardization"] = {k: v for k, v in std.items()
                                   if k in ("t_mean", "t_scale", "sent_mean", "sent_scale")}
    products["run_seconds"] = round(time.time() - started, 1)
    products["generated_at"] = datetime.now(timezone.utc).isoformat()
    LOG.info("prior-placeholder products built in %.1fs (NO inference — UI demo only)",
             products["run_seconds"])
    return products


# --------------------------------------------------------------------------- #
# Synthetic data (tests + P5 exit run) — plausible season shapes, no network
# --------------------------------------------------------------------------- #

SYNTHETIC_NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
                   "Golf", "Hotel", "India", "Juliet", "Kilo", "Lima"]


def synthetic_roster(n: int = 12) -> list[dict[str, Any]]:
    """Roster matching synthetic_cpi_payload for any n: the LAST three housemates
    exit (evicted wk2 / walked wk3 / evicted wk4), mirroring the real season's
    walkout + evictions; the FIRST two hold the Gambit (weeks 1-5)."""
    names = SYNTHETIC_NAMES[:n]
    exits = {names[-1]: (2, "evicted"), names[-2]: (3, "walked"),
             names[-3]: (4, "evicted")}
    return [{"name": nm, "full_name": nm, "sex": "M" if i % 2 == 0 else "F",
             "aliases": [nm], "photo": f"assets/photos/{nm.lower()}.jpg",
             "entry_week": 1, "status": "active",
             "exit_week": exits[nm][0] if nm in exits else None,
             "exit_type": exits[nm][1] if nm in exits else None}
            for i, nm in enumerate(names)]


# backward-compatible alias (full 12-housemate roster)
SYNTHETIC_HOUSEMATES = synthetic_roster(12)


def synthetic_cpi_payload(seed: int = 42, n_housemates: int = 12, weeks: int = 6,
                          finale_week: int = 10) -> dict[str, Any]:
    """A synthetic daily_cpi.json payload in the real schema: one dominant
    housemate, one rising, a weekly-varying Gambit pair (weeks 1-5), a week-3
    walkout, and a week-4 eviction — positions scale with n_housemates."""
    rng = np.random.default_rng(seed)
    names = SYNTHETIC_NAMES[:n_housemates]
    housemates = synthetic_roster(n_housemates)
    exit_plan = {names[-1]: (2, "evicted"), names[-2]: (3, "walked"),
                 names[-3]: (4, "evicted")}
    base_mu = rng.normal(2.6, 0.5, size=n_housemates)
    base_mu[0] += 0.9                       # Alpha: dominant
    beta_hm = rng.normal(0.0, 0.08, size=n_housemates)
    beta_hm[1] += 0.25                      # Bravo: rising
    records: list[dict[str, Any]] = []
    for t in range(1, weeks + 1):
        for i, n in enumerate(names):
            ex_w, ex_t = exit_plan.get(n, (None, None))
            if ex_w and t > ex_w:
                continue
            status = "active" if not ex_w or t < ex_w else ex_t
            mu = base_mu[i] + beta_hm[i] * (t - 1) + rng.normal(0, 0.35)
            cpi = float(np.clip(mu / 6.0 + rng.normal(0, 0.08), 0.0, 1.0))
            # guarantee at least one t_now nominee so the at-risk panel is live
            atrisk = int(rng.random() < 0.4) or int(t == weeks and n == names[2])
            records.append({
                "season": 11, "week": t, "week_start": f"2026-07-{25 + 7 * (t - 1):02d}",
                "housemate": n, "comments": None, "shares": None,
                "article_mentions": int(rng.integers(5, 40)),
                "headline_features": int(rng.integers(0, 6)),
                "cpi": round(cpi, 6), "sentiment": round(rng.normal(0.1, 0.2), 6),
                "at_risk": atrisk,
                "twist": 1, "gambit_flag": int(n in (names[0], names[1]) and t <= 5),
                "backfilled": False, "status": status, "sources": ["synthetic"],
                "missing_weeks": [],
            })
    return {"generated_at": "2026-01-01T00:00:00Z", "season": 11,
            "weeks_built": list(range(1, weeks + 1)), "missing_weeks": [], "records": records}


SYNTHETIC_HOUSEMATES = [
    {"name": n, "full_name": n, "sex": "M" if i % 2 == 0 else "F", "aliases": [n],
     "photo": f"assets/photos/{n.lower()}.jpg", "entry_week": 1, "status": "active",
     "exit_week": {"India": 4, "Kilo": 3, "Lima": 2}.get(n),
     "exit_type": {"India": "evicted", "Kilo": "walked", "Lima": "evicted"}.get(n)}
    for i, n in enumerate(["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
                           "Golf", "Hotel", "India", "Juliet", "Kilo", "Lima"])
]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_summary(products: dict[str, Any]) -> None:
    print("\n=== P5 modeling run summary ===")
    print(f"precision: {products['precision']}   rhat_max: {products['rhat_max']}   "
          f"candidates R-hat: {products['rhat_by_candidate']}")
    print(f"BMA weights: {products['model_weights']}")
    p = products["podium"]
    print(f"podium: 1) {p['winner']['name']} ({p['winner']['prob']:.2f})  "
          f"2) {p['runner_up']['name']} ({p['runner_up']['prob']:.2f})  "
          f"3) {p['second_runner_up']['name']} ({p['second_runner_up']['prob']:.2f})")
    print(f"trend projection (secondary): {products['trend_projection']['podium']}")
    print(f"at risk (relative hazard): "
          f"{[(r['name'], round(r['relative_hazard'], 2)) for r in products['at_risk']]}")
    top = sorted((h for h in products['housemates'] if h['status'] == 'active'),
                 key=lambda h: -h['p_rank_1'])[:5]
    for h in top:
        print(f"  {h['name']:<12} P(#1)={h['p_rank_1']:.2f}  P(top3)={h['p_top3']:.2f}  "
              f"P(top5)={h['p_top5']:.2f}  median={h['win_prob_median']:.3f} "
              f"HDI89={h['hdi_89']}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="P5 modeling core (weekly standings model)")
    ap.add_argument("--selftest", action="store_true", help="tiny synthetic end-to-end run")
    ap.add_argument("--synthetic", action="store_true", help="use the synthetic season")
    ap.add_argument("--full", action="store_true", help="full spec sampling (4 x 2000)")
    ap.add_argument("--lite", action="store_true", help="reduced sampling (labelled)")
    ap.add_argument("--prior-check", action="store_true", help="prior predictive sanity")
    ap.add_argument("--prior-placeholder", action="store_true",
                    help="no-sampling products from the prior predictive (UI/deploy demo; "
                         "labelled placeholder, never publish as predictions)")
    ap.add_argument("--out", default=None,
                    help="write products JSON here (e.g. data/predictions.json) in "
                         "prior-placeholder mode")
    ap.add_argument("--record", default=None, help="run-record filename under notebooks/")
    ap.add_argument("--draws", type=int, default=None,
                    help="override posterior draws per chain (diagnostic probes)")
    ap.add_argument("--chains", type=int, default=None,
                    help="override chain count (diagnostic probes)")
    ap.add_argument("--tune", type=int, default=None,
                    help="override tuning iterations (diagnostic probes)")
    ap.add_argument("--candidates", nargs="*", default=None,
                    choices=sorted(set(BMA_CANDIDATES)),
                    help="subset of BMA candidates to sample (probes)")
    ap.add_argument("--resume", nargs="?", const=".mcmc_checkpoints", default=None,
                    help="checkpoint idata per candidate under this dir; if files "
                         "exist they are loaded instead of resampling (crash insurance)")
    args = ap.parse_args(argv)

    if args.selftest:
        payload = synthetic_cpi_payload(weeks=4, n_housemates=6)
        hms = synthetic_roster(6)
        lite = True
    elif args.synthetic:
        payload = synthetic_cpi_payload()
        hms = synthetic_roster(12)
        lite = args.lite
    else:
        with open(DAILY_CPI, encoding="utf-8") as fh:
            payload = json.load(fh)
        with open(CONFIG_DIR / "housemates.json", encoding="utf-8") as fh:
            hms = json.load(fh)["housemates"]
        lite = args.lite

    if args.prior_placeholder:
        products = run_prior_placeholder(payload, hms)
        _print_summary(products)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(products, indent=1, ensure_ascii=False),
                                encoding="utf-8")
            LOG.info("placeholder products written: %s (precision=%s)",
                     out_path, products["precision"])
        return 0

    products = run_inference(payload, hms, lite=lite, full=args.full,
                             prior_check=args.prior_check,
                             draws_override=args.draws, chains_override=args.chains,
                             candidates_override=args.candidates,
                             checkpoint_dir=args.resume, tune_override=args.tune)
    _print_summary(products)
    if args.out:  # real runs also honour --out (P6 handoff to the runner)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(products, indent=1, ensure_ascii=False),
                            encoding="utf-8")
        LOG.info("products written: %s (precision=%s)", out_path, products["precision"])

    record_name = args.record or ("run_record_synthetic.json" if (args.synthetic or args.selftest)
                                  else "run_record_latest.json")
    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P5", "mode": ("selftest" if args.selftest else
                                "synthetic" if args.synthetic else "real-data"),
        "priors": PRIORS, "seed": MASTER_SEED,
        "rhat_max": products["rhat_max"], "rhat_by_candidate": products["rhat_by_candidate"],
        "divergences_by_candidate": products["divergences_by_candidate"],
        "standardization": products["standardization"], "precision": products["precision"],
        "podium": products["podium"], "trend_projection": products["trend_projection"],
        "model_weights": products["model_weights"], "run_seconds": products["run_seconds"],
        "polls": products.get("polls"),
    }
    path = RUN_RECORD_DIR / record_name
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    LOG.info("run record written: %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
