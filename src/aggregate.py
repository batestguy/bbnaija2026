"""BBNaija 2026 Predictor — E2 aggregation & products engine.

Implements the frozen Readme.txt §3 sequence with the owner's decided deltas
(poll-matrix-engine-spec.md §5, §12):

  filter (window, active-set, >=2-covered) ->
  weights w = q * min(n, cap) * lambda^Dt ->
  full-share aggregation (per-row renormalisation over covered names) ->
  carry-forward for poll-uncovered actives (flagged, never fabricated) ->
  constraints with soften-on-conflict (top_N/bottom_N; every application
  logged with before/after shares) ->
  renormalise over share-eligible actives ->
  bootstrap B replicates (resample rows with replacement proportional to w) ->
  products: share=P(win), 89% bootstrap intervals, P(A>B), rank chips,
  podium slot probabilities, momentum = dShare WoW, statistical ties.

Honesty rules encoded here:
  * 89% intervals (owner override of Readme §3.6's 95%) — interval_percent
    comes from config, so the override is recorded, never silent.
  * Carried shares are flagged `carried`; never-measured actives get the
    MINIMUM measured share as an unmeasured floor (conservative, logged) so
    the standings table stays complete without inventing support.
  * Gambit housemates never reach this module (excluded in poll_matrix) —
    the renormalisation set is exactly the share-eligible actives.
  * No new sampling machinery: rank/podium probabilities are replicate
    fractions, per spec §5.7.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

LOG = logging.getLogger("aggregate")

ROOT = Path(__file__).resolve().parent.parent


def load_engine_config() -> dict[str, Any]:
    """Single tunables file (Readme §5.4 contract)."""
    import json
    with open(ROOT / "config" / "poll_engine.json", encoding="utf-8") as fh:
        return json.load(fh)


def build_matrix_rows(week: int, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Bridge to the E1 matrix builder (keeps aggregate import-light)."""
    from src.poll_matrix import build_matrix
    return build_matrix(week, cfg)


# --------------------------------------------------------------------------- #
# Step 1 — filter (Readme §3.1)
# --------------------------------------------------------------------------- #

def filter_window(rows: list[dict[str, Any]], current_week: int,
                  window_weeks: int) -> list[dict[str, Any]]:
    """Rows from the last `window_weeks` weeks (current week included)."""
    lo = current_week - window_weeks + 1
    kept = [r for r in rows if lo <= int(r["week"]) <= current_week]
    dropped = len(rows) - len(kept)
    if dropped:
        LOG.info("window filter: dropped %d row(s) older than week %d", dropped, lo)
    return kept


def compute_weights(rows: list[dict[str, Any]], current_week: int,
                    cfg: dict[str, Any]) -> np.ndarray:
    """w_k = q_k * min(n_k, cap) * lambda^Dt_k  (Readme §3.2; sample_size is
    stored already capped by the matrix builder, min() here is belt-and-braces)."""
    cap = float(cfg["cap"])
    lam = float(cfg["lambda_decay"])
    w = np.empty(len(rows), dtype=float)
    for k, r in enumerate(rows):
        age = current_week - int(r["week"])
        w[k] = float(r["source_grade"]) * min(float(r["sample_size"]), cap) * (lam ** age)
    return w


# --------------------------------------------------------------------------- #
# Step 3 — full-share aggregation for one replicate (Readme §3.3)
# --------------------------------------------------------------------------- #

def _row_shares_over(row: dict[str, Any], eligible: set[str]) -> dict[str, float]:
    """The row's housemate columns, restricted to eligible actives, renormalised
    over that covered set (Readme §3.3 per-observation renormalisation)."""
    covered = {name: float(v) for name, v in row.items()
               if name not in _META_COLS and name in eligible and v is not None
               and not (isinstance(v, float) and np.isnan(v))}
    total = sum(covered.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in covered.items()}


_META_COLS = frozenset({
    "obs_id", "source_name", "source_grade", "obs_type", "sample_size",
    "timestamp", "week", "active_set", "poll_url", "collection_method",
    "snapshot_id", "n_collapsed", "provenance", "carried",
})


def aggregate_shares(rows: list[dict[str, Any]], weights: np.ndarray,
                     counts: np.ndarray, eligible: set[str]) -> dict[str, float]:
    """Weighted mean of per-row share vectors over full_share rows only."""
    S = {name: 0.0 for name in eligible}
    wsum = 0.0
    for k, row in enumerate(rows):
        c = int(counts[k])
        if c <= 0 or row["obs_type"] != "full_share":
            continue
        shares = _row_shares_over(row, eligible)
        if not shares:
            continue
        wk = float(weights[k]) * c
        for name, s in shares.items():
            S[name] += wk * s
        wsum += wk
    if wsum <= 0:
        return {}
    covered = {name for name, v in S.items() if v > 0}
    for name in covered:
        S[name] /= wsum
    return S


# --------------------------------------------------------------------------- #
# Step 4 — constraints with soften-on-conflict (Readme §3.4 + spec §5.5)
# --------------------------------------------------------------------------- #

def apply_constraints(S: dict[str, float], rows: list[dict[str, Any]],
                      weights: np.ndarray, counts: np.ndarray,
                      cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply top_N/bottom_N constraint rows to S in place; return an audit log.

    Ordering-agreement rule (owner decision #12): when the constraint's implied
    ordering already agrees with the aggregate, apply Readme §3.4 exactly
    (cap/floor at m*(1∓eps)). On conflict, pull the violating shares HALFWAY
    toward the bound instead — never a full reorder from one C-grade row."""
    eps = float(cfg.get("epsilon_constraint", 0.01))
    halfway = float(cfg.get("constraint_rules", {}).get("halfway_factor", 0.5))
    log: list[dict[str, Any]] = []

    # deterministic order: higher grade first, then source name
    crows = [(k, r) for k, r in enumerate(rows)
             if r["obs_type"] in ("top_N", "bottom_N") and int(counts[k]) > 0]
    crows.sort(key=lambda kr: (-float(kr[1]["source_grade"]), kr[1]["source_name"]))

    for k, row in crows:
        eligible = set(S)
        # flagged = names explicitly carrying a 1 flag in the row
        flagged = sorted(name for name in eligible
                         if name in row and row[name] is not None
                         and not (isinstance(row[name], float) and np.isnan(row[name]))
                         and float(row[name]) == 1)
        others = sorted(name for name in eligible if name not in flagged)
        if not flagged or not others:
            continue
        kind = row["obs_type"]
        if kind == "bottom_N":
            m_out = min(S[name] for name in others)
            bound = m_out * (1 - eps)
            # agreement = ALL flagged already at/below ALL others
            agree = max(S[name] for name in flagged) <= min(S[name] for name in others)
            violations = [name for name in flagged if S[name] > bound]
            before = {name: round(S[name], 6) for name in violations}
            for name in violations:
                target = bound
                S[name] = target if agree else S[name] + halfway * (target - S[name])
            log.append({"source": row["source_name"], "kind": kind,
                        "flagged": flagged, "agreed": bool(agree),
                        "before": before,
                        "after": {name: round(S[name], 6) for name in violations}})
        else:  # top_N
            m_out = max(S[name] for name in others)
            bound = m_out * (1 + eps)
            # agreement = ALL flagged already at/above ALL others
            agree = min(S[name] for name in flagged) >= max(S[name] for name in others)
            violations = [name for name in flagged if S[name] < bound]
            before = {name: round(S[name], 6) for name in violations}
            for name in violations:
                target = bound
                S[name] = target if agree else S[name] + halfway * (target - S[name])
            log.append({"source": row["source_name"], "kind": kind,
                        "flagged": flagged, "agreed": bool(agree),
                        "before": before,
                        "after": {name: round(S[name], 6) for name in violations}})
        if log[-1]["before"]:
            LOG.info("constraint %s (%s): %s — after: %s", row["source_name"], kind,
                     "agreed" if agree else "CONFLICT-softened", log[-1]["after"])
    return log


# --------------------------------------------------------------------------- #
# Carry-forward + unmeasured floor (spec §5.4, owner decision #20)
# --------------------------------------------------------------------------- #

def apply_carry_forward(S: dict[str, float], prev_shares: dict[str, float] | None,
                        cfg: dict[str, Any], warn: bool = True
                        ) -> tuple[dict[str, float], list[str], list[str]]:
    """Uncovered actives inherit last week's aggregated share (flagged carried);
    never-measured actives get the minimum measured share (flagged unmeasured).
    Returns (S, carried_names, unmeasured_names). `warn=False` silences the
    console warning (bootstrap replicates call this hundreds of times)."""
    if not cfg.get("carry_forward", {}).get("enabled", True):
        return S, [], []
    measured = {name for name, v in S.items() if v > 0}
    uncovered = [name for name in S if name not in measured]
    carried: list[str] = []
    unmeasured: list[str] = []
    if not uncovered:
        return S, carried, unmeasured
    floor = min((S[name] for name in measured), default=0.0)
    for name in uncovered:
        if prev_shares and name in prev_shares and prev_shares[name] > 0:
            S[name] = float(prev_shares[name])
            carried.append(name)
        else:
            S[name] = floor
            unmeasured.append(name)
    if carried and warn:
        LOG.info("carry-forward applied to: %s", ", ".join(sorted(carried)))
    if unmeasured and warn:
        LOG.warning("unmeasured actives floored at min measured share (%.4f): %s",
                    floor, ", ".join(sorted(unmeasured)))
    return S, carried, unmeasured


# --------------------------------------------------------------------------- #
# Step 5 — renormalise (Readme §3.5)
# --------------------------------------------------------------------------- #

def renormalise(S: dict[str, float]) -> dict[str, float]:
    total = sum(S.values())
    if total <= 0:
        return {name: 0.0 for name in S}
    return {name: v / total for name, v in S.items()}


# --------------------------------------------------------------------------- #
# Step 6 — bootstrap (Readme §3.6, 89% owner override)
# --------------------------------------------------------------------------- #

def bootstrap(rows: list[dict[str, Any]], weights: np.ndarray,
              eligible: set[str], cfg: dict[str, Any],
              prev_shares: dict[str, float] | None) -> tuple[np.ndarray, list[list[dict]]]:
    """B replicates, two uncertainty layers (both implied by the Readme's
    sample-size-aware design):
      1. BETWEEN-poll: resample observations with replacement ∝ w
         (multinomial over rows) — captures source disagreement.
      2. WITHIN-poll: per selected copy, draw the poll's voters
         (multinomial over the row's shares with n = its capped sample_size)
         — captures sampling noise. Without this layer a single-poll window
         would produce ZERO-width CIs and falsely decisive P(A>B) = 0.5
         ties everywhere; with it, thin data widens honestly.
    Reruns carry + constraints + renormalise per replicate. The POINT estimate
    (build_products) never uses voter noise — published S_i stays exactly the
    hand-verifiable weighted aggregation.

    Returns (rep_shares matrix [B x n_names], constraint_logs per replicate)."""
    B = int(cfg["bootstrap_replicates"])
    seed = int(cfg.get("bootstrap_seed", 0))
    rng = np.random.default_rng(seed)
    names = sorted(eligible)
    idx = {name: i for i, name in enumerate(names)}
    cap = float(cfg["cap"])

    w = weights.astype(float)
    if w.sum() <= 0:
        p = np.full(len(rows), 1.0 / max(len(rows), 1))
    else:
        p = w / w.sum()
    counts = rng.multinomial(max(len(rows), 1), p, size=B)  # [B, n_rows]

    # precompute per-row covered shares + n over eligible set
    row_info = []
    for k, row in enumerate(rows):
        if row["obs_type"] == "full_share":
            base = _row_shares_over(row, eligible)
            n_row = int(min(float(row["sample_size"]), cap))
            row_info.append((sorted(base), np.array([base[n] for n in sorted(base)]),
                             n_row) if base else (None, None, 0))
        else:
            row_info.append((None, None, 0))

    reps = np.zeros((B, len(names)), dtype=float)
    all_logs: list[list[dict]] = []
    for b in range(B):
        acc = {name: 0.0 for name in names}
        wsum = 0.0
        for k, row in enumerate(rows):
            c = int(counts[b][k])
            if c <= 0 or row["obs_type"] != "full_share":
                continue
            covered, pv, n_row = row_info[k]
            if not covered or n_row <= 0:
                continue
            for _copy in range(c):
                draws = rng.multinomial(n_row, pv)
                wk = float(weights[k])
                for name, v in zip(covered, draws):
                    acc[name] += wk * (v / n_row)
                wsum += wk
        if wsum <= 0:
            continue
        # Keep ALL eligible names (zeros included) so the carry-forward floor
        # behaves EXACTLY as in the point estimate — filtering zeros here
        # would drop floored housemates from the renormalisation set and
        # shift replicate shares away from the published point shares.
        S = {name: acc[name] / wsum for name in names}
        S, _, _ = apply_carry_forward(S, prev_shares, cfg, warn=False)
        logs = apply_constraints(S, rows, weights, counts[b], cfg)
        S = renormalise(S)
        for name, v in S.items():
            reps[b, idx[name]] = v
        all_logs.append(logs)
    return reps, all_logs


# --------------------------------------------------------------------------- #
# Products (spec §5.7 — share = P(win); replicates give everything else)
# --------------------------------------------------------------------------- #

def rank_probabilities(reps: np.ndarray, names: list[str]) -> dict[str, dict[str, float]]:
    """P(#1), P(top-3), P(top-5) = replicate fractions (spec §5.7)."""
    order = np.argsort(-reps, axis=1, kind="stable")   # [B, n] name indices
    out = {n: {"p_rank_1": 0.0, "p_top3": 0.0, "p_top5": 0.0} for n in names}
    B = reps.shape[0]
    for b in range(B):
        for pos, name_idx in enumerate(order[b]):
            n = names[name_idx]
            if pos == 0:
                out[n]["p_rank_1"] += 1 / B
            if pos < 3:
                out[n]["p_top3"] += 1 / B
            if pos < 5:
                out[n]["p_top5"] += 1 / B
    return out


def pairwise_beat(reps: np.ndarray, names: list[str]) -> dict[tuple[str, str], float]:
    """P(A>B) = fraction of replicates where S_A > S_B (Readme §3.6)."""
    out: dict[tuple[str, str], float] = {}
    B = reps.shape[0]
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i < j:
                out[(a, b)] = float(np.mean(reps[:, i] > reps[:, j]))
    return out


def podium_from_replicates(reps: np.ndarray, names: list[str]) -> tuple[dict[str, dict], dict[str, float]]:
    """Podium slots with replicate-fraction slot probabilities."""
    order = np.argsort(-reps, axis=1, kind="stable")
    B = reps.shape[0]
    n_slots = min(3, len(names))
    counts = np.zeros((3, len(names)), dtype=float)
    for b in range(B):
        for slot in range(n_slots):
            counts[slot, order[b][slot]] += 1
    slot_p = [0.0, 0.0, 0.0]
    podium = {}
    labels = ("winner", "runner_up", "second_runner_up")
    used: set[str] = set()
    for slot, label in enumerate(labels):
        if slot >= len(names):
            podium[label] = {"name": None, "prob": 0.0}   # degrade honestly (<3 actives)
            continue
        # most frequent name in this slot not already assigned a higher slot
        freq = counts[slot].copy()
        for u in used:
            freq[names.index(u)] = -1.0
        winner_idx = int(np.argmax(freq))
        name = names[winner_idx]
        used.add(name)
        slot_p[slot] = float(freq[winner_idx] / B)
        podium[label] = {"name": name, "prob": round(slot_p[slot], 4)}
    return podium, slot_p


def statistical_ties(point: dict[str, float], reps: np.ndarray,
                     names: list[str], cfg: dict[str, Any]) -> dict[str, list[str]]:
    """Adjacent ranked pairs with P(A>B) < 0.60 are 'too close to call' ties
    (Readme §4 decision rules). Returns name -> tied-with list."""
    too_close = float(cfg.get("decision_rules", {}).get("too_close_p_ab", 0.60))
    ranked = sorted(names, key=lambda n: -point[n])
    rep_idx = {n: i for i, n in enumerate(names)}
    ties: dict[str, list[str]] = {}
    for a, b in zip(ranked, ranked[1:]):
        pa = float(np.mean(reps[:, rep_idx[a]] > reps[:, rep_idx[b]]))
        if pa < too_close:
            ties.setdefault(a, []).append(b)
            ties.setdefault(b, []).append(a)
    return ties


def canonicalize_rows(rows: list[dict[str, Any]],
                      housemates_cfg: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Matrix rows key housemate columns by slug id (keivo); aggregation works
    on canonical names (Keivo). Rewrite the housemate columns in place; unknown
    slugs are dropped with a warning (upstream quarantine should have caught
    them — never silently promoted into standings)."""
    from src.poll_matrix import housemate_id, CORE_COLUMNS
    slug_to_name = {housemate_id(h["name"]): h["name"] for h in housemates_cfg}
    # idempotence: rows already carrying canonical-name columns pass through
    for h in housemates_cfg:
        slug_to_name.setdefault(h["name"], h["name"])
    out = []
    for r in rows:
        row = dict(r)
        known: dict[str, Any] = {}
        for k, v in row.items():
            if k in CORE_COLUMNS:
                continue
            if k in slug_to_name:
                known[slug_to_name[k]] = v
            else:
                LOG.warning("dropping unknown housemate column %r from obs %s", k,
                            r.get("obs_id", "?"))
        row.clear()
        row.update({**{k: v for k, v in r.items() if k in CORE_COLUMNS}, **known})
        out.append(row)
    return out


def build_products(rows: list[dict[str, Any]], current_week: int,
                   cfg: dict[str, Any], housemates_cfg: list[dict[str, Any]],
                   prev_products: dict[str, Any] | None = None) -> dict[str, Any]:
    """Full aggregation for `current_week` -> predictions.json-shaped dict.

    `prev_products` (last good predictions.json) supplies previous shares for
    momentum and carry-forward; absent on a cold start (momentum=None)."""
    rows = canonicalize_rows(rows, housemates_cfg)
    # eligible = active (not exited) housemates
    def _is_active(h: dict[str, Any]) -> bool:
        return h.get("status") == "active" and h.get("exit_week") is None

    actives = sorted(h["name"] for h in housemates_cfg if _is_active(h))
    # spec §6: housemates in an ACTIVE gambit period this week are excluded
    # from the matrix AND from standings — they surface in auto_finalists.
    # (Currently inert: Flora/Aikou released wk6; driven by config/twist.json.)
    from src.poll_matrix import load_gambit_names
    gambit_now = load_gambit_names(current_week)
    eligible = set(actives) - gambit_now
    hm_by_name0 = {h["name"]: h for h in housemates_cfg}
    auto_finalists = [{"name": n, "status": hm_by_name0[n].get("status", "active"),
                       "photo": hm_by_name0[n].get("photo")}
                      for n in sorted(gambit_now & set(actives))]

    prev_shares: dict[str, float] = {}
    prev_history: dict[str, list] = {}
    prev_week = prev_products.get("week") if prev_products else None
    # Model purity: legacy (MCMC-era) products can seed NOTHING. Carry-forward
    # and momentum may only chain from this engine's own prior output —
    # otherwise retired-model medians would leak into poll-engine standings.
    if prev_products and prev_products.get("engine", {}).get("name") != "poll_matrix":
        LOG.info("prev products are from a non-poll-matrix engine (%s) — "
                 "ignored (cold start, momentum=None, unmeasured floor applies)",
                 prev_products.get("engine", {}).get("name", "legacy"))
        prev_products = None
        prev_week = None
    if prev_products:
        for h in prev_products.get("housemates", []):
            nm = h.get("name")
            hist = list(h.get("history", []))
            # same-week rerun: drop the stale row for THIS week so momentum
            # still compares against last week and history never double-appends
            if prev_week == current_week and hist \
                    and int(hist[-1].get("week", -1)) == current_week:
                hist = hist[:-1]
            prev_history[nm] = hist
            if hist and int(hist[-1].get("week", -1)) < current_week:
                prev_shares[nm] = float(hist[-1].get("median", 0.0))

    window = filter_window(rows, current_week, int(cfg["window_weeks"]))
    weights = compute_weights(window, current_week, cfg)
    if not window:
        raise ValueError("no observation rows in window — refusing to fabricate standings")

    # point estimate
    S = aggregate_shares(window, weights, np.ones(len(window), dtype=int), eligible)
    if not S:
        raise ValueError("no full-share rows aggregated — refusing to fabricate standings")
    S, carried, unmeasured = apply_carry_forward(S, prev_shares, cfg)
    constraint_log = apply_constraints(S, window, weights,
                                       np.ones(len(window), dtype=int), cfg)
    S = renormalise(S)

    # bootstrap replicates
    reps, _ = bootstrap(window, weights, eligible, cfg, prev_shares)
    names = sorted(eligible)
    idx = {n: i for i, n in enumerate(names)}

    lo_pct = (100.0 - float(cfg.get("interval_percent", 89))) / 2.0
    hi_pct = 100.0 - lo_pct
    ci = {n: [float(np.percentile(reps[:, idx[n]], lo_pct)),
              float(np.percentile(reps[:, idx[n]], hi_pct))] for n in names}
    ranks = rank_probabilities(reps, names)
    beats = pairwise_beat(reps, names)
    pairwise = {a: {b: round(p, 4) for (a2, b), p in beats.items() if a2 == a}
                for a in names}
    podium, _ = podium_from_replicates(reps, names)
    ties = statistical_ties(S, reps, names, cfg)

    # momentum = dShare WoW (decision #13) from prev products
    momentum: dict[str, float | None] = {}
    for n in names:
        prev = prev_shares.get(n)
        momentum[n] = (round(S[n] - prev, 4) if prev is not None else None)

    # at-risk: lowest shares first + constraint flags (no Cox hazard anymore)
    bottom_flagged = {n for c in constraint_log if c["kind"] == "bottom_N"
                      for n in c["flagged"]}
    at_risk = [{"name": n, "share": round(S[n], 4),
                "bottom_n_flag": n in bottom_flagged}
               for n in sorted(names, key=lambda x: S[x])][:5]

    hm_by_name = {h["name"]: h for h in housemates_cfg}
    housemates_out = []
    for n in names:
        h = hm_by_name.get(n, {})
        hist = list(prev_history.get(n, []))
        if hist and int(hist[-1].get("week", -1)) == current_week:
            hist[-1] = {"week": current_week, "median": round(S[n], 6),
                        "hdi_89": [round(ci[n][0], 6), round(ci[n][1], 6)]}
        else:
            hist.append({"week": current_week, "median": round(S[n], 6),
                         "hdi_89": [round(ci[n][0], 6), round(ci[n][1], 6)]})
        housemates_out.append({
            "name": n,
            "status": h.get("status", "active"),
            "share": round(S[n], 6),
            "p_rank_1": round(ranks[n]["p_rank_1"], 4),
            "p_top3": round(ranks[n]["p_top3"], 4),
            "p_top5": round(ranks[n]["p_top5"], 4),
            "ci_89": [round(ci[n][0], 6), round(ci[n][1], 6)],
            "momentum": momentum[n],
            "carried": n in carried,
            "unmeasured": n in unmeasured,
            "statistical_tie_with": sorted(ties.get(n, [])),
            "history": hist,
        })

    sources_in_window = sorted({r["source_name"] for r in window})
    products = {
        "generated_at": None,  # runner stamps UTC now
        "precision": "full",
        "week": current_week,
        "podium": podium,
        "housemates": housemates_out,
        "at_risk": at_risk,
        "engine": {
            "name": "poll_matrix",
            "spec": "poll-matrix-engine-spec.md (2026-09-22)",
            "params": {k: cfg[k] for k in
                       ("window_weeks", "cap", "lambda_decay", "epsilon_constraint",
                        "bootstrap_replicates", "bootstrap_seed", "interval_percent")
                       if k in cfg},
            "grades": cfg.get("grades", {}),
        },
        "polls": {
            "anchor_applied": False,
            "engine_note": "poll-matrix engine: polls ARE the likelihood, not a prior anchor",
            "sources_in_window": sources_in_window,
            "constraint_log": constraint_log,
            "carried": sorted(carried),
            "unmeasured_floored": sorted(unmeasured),
        },
        "pairwise": pairwise,
        "auto_finalists": auto_finalists,
        "data_sufficiency": {
            "rows_in_window": len(window),
            "full_share_rows": sum(1 for r in window if r["obs_type"] == "full_share"),
            "constraint_rows": sum(1 for r in window if r["obs_type"] != "full_share"),
            "sources_reporting": sources_in_window,
            "weeks_in_window": sorted({int(r["week"]) for r in window}),
        },
    }
    return products


def main(argv: list[str] | None = None) -> int:
    """E3 stage entrypoint: python -m src.aggregate [--week N] [--out PATH]

    Reads the matrix via src.poll_matrix.build_matrix, the last-good
    predictions.json for momentum/carry-forward, writes the products JSON the
    runner then schema-gates. Never touches the network."""
    import argparse
    import json
    import sys
    from datetime import datetime, timezone

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Poll-matrix aggregation stage (E2/E3)")
    ap.add_argument("--week", type=int, default=None,
                    help="season week (default: calendar-true current week)")
    ap.add_argument("--out", default=str(ROOT / "data" / "predictions.json"))
    args = ap.parse_args(argv)

    cfg = load_engine_config()
    week = args.week
    if week is None:
        from src import scrape_blogs as sb
        week = sb.current_week(sb.load_season())

    rows = build_matrix_rows(week, cfg)
    from src import scrape_blogs as sb
    housemates_cfg = sb.load_housemates()

    prev_products = None
    last_good = ROOT / "data" / ".last_good_predictions.json"
    docs_pred = ROOT / "docs" / "predictions.json"
    for candidate in (last_good, docs_pred):
        if candidate.exists():
            try:
                with open(candidate, encoding="utf-8") as fh:
                    prev_products = json.load(fh)
                break
            except (json.JSONDecodeError, OSError):
                continue

    products = build_products(rows, week, cfg, housemates_cfg, prev_products)
    products["generated_at"] = datetime.now(timezone.utc).isoformat()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(products, indent=1, ensure_ascii=False), encoding="utf-8")
    LOG.info("products written: %s (week %d, %d rows in window)",
             out, week, products["data_sufficiency"]["rows_in_window"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
