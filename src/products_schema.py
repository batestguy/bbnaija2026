"""predictions.json schema gate (P6.3 step 1 / P8.2; v2 since E4).

One shared validator: the Saturday runner validates before writing, and the
deploy workflow validates before publishing — a bad file never goes live.

SHAPE-AWARE (E4.1, spec §9 adapt-in-place): the payload's `engine.name`
selects the rule set —
  * `poll_matrix` (v2, the engine since 2026-09-22): share=P(win) standings,
    89% bootstrap CIs, share-based at_risk, engine params recorded.
  * anything else (legacy MCMC/BMA, retired in place): the original P5/P6
    rules, so the last published legacy file stays deployable until the
    first certified poll-matrix run replaces it.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)

PRECISION_OK = {"full", "lite", "prior-predictive"}
STATUS_OK = {"active", "evicted", "walked", "disqualified"}
SLOT_KEYS = ("winner", "runner_up", "second_runner_up")


def _is_poll_matrix(products: dict) -> bool:
    return (products.get("engine") or {}).get("name") == "poll_matrix"

# Marketplace rule: if the freshest predictions are older than this, the deploy
# still publishes (stale beats absent) but the workflow logs a warning. The
# dashboard renders its own staleness badge from generated_at regardless.
STALE_AFTER = timedelta(days=8)


class SchemaError(ValueError):
    """predictions.json failed the deploy/runner schema gate."""


def validate_products(products: dict, *, require_placeholder_consistency: bool = True) -> list[str]:
    """Validate the predictions.json payload dict. Returns warnings; raises SchemaError."""
    warns: list[str] = []

    def req(cond: bool, msg: str) -> None:
        if not cond:
            raise SchemaError(msg)

    # --- required top-level fields -------------------------------------------
    for key in ("generated_at", "precision", "podium", "housemates"):
        req(key in products, f"missing required field: {key}")

    req(products["precision"] in PRECISION_OK,
        f"precision must be one of {sorted(PRECISION_OK)}, got {products['precision']!r}")

    try:
        generated = datetime.fromisoformat(products["generated_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError) as e:
        raise SchemaError(f"generated_at is not ISO-8601: {products['generated_at']!r}") from e
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - generated > STALE_AFTER > timedelta(0):
        warns.append("generated_at is stale (> 8 days) — publishing anyway; dashboard badge applies")

    # --- podium ---------------------------------------------------------------
    podium = products["podium"]
    req(isinstance(podium, dict) and set(podium) >= set(SLOT_KEYS),
        f"podium must contain {SLOT_KEYS}, got {sorted(podium)}")
    poll_engine = _is_poll_matrix(products)
    names = [podium[k].get("name") for k in SLOT_KEYS]
    if poll_engine:
        # honest degradation: fewer than 3 actives => trailing slots may be null
        n_active = sum(1 for h in products["housemates"] if h.get("status") == "active")
        n_expected = min(3, n_active)
        filled = [n for n in names if isinstance(n, str) and n]
        req(len(filled) == n_expected,
            f"podium must fill {n_expected} slots for {n_active} actives, got {filled}")
        req(len(set(filled)) == len(filled), f"podium slots must be distinct, got {filled}")
    else:
        req(all(isinstance(n, str) and n for n in names),
            f"podium slots must carry names, got {names}")
        req(len(set(names)) == 3, f"podium slots must be distinct people, got {names}")

    # --- housemates -----------------------------------------------------------
    hms = products["housemates"]
    min_hms = 1 if _is_poll_matrix(products) else 2   # v2 degrades honestly to 1 active
    req(isinstance(hms, list) and len(hms) >= min_hms,
        f"housemates must be a list with at least {min_hms} entries")
    req(len({h.get("name") for h in hms}) == len(hms),
        "housemate names must be unique")
    for h in hms:
        nm = h.get("name") or "<unnamed>"
        req(h.get("status") in STATUS_OK,
            f"{nm}: status {h.get('status')!r} not in {sorted(STATUS_OK)}")
        req(isinstance(h.get("p_rank_1"), (int, float)),
            f"{nm}: p_rank_1 must be numeric")
        req(isinstance(h.get("history"), list) and len(h["history"]) >= 1,
            f"{nm}: history must have at least one row")
        for row in h["history"]:
            req(isinstance(row.get("median"), (int, float)),
                f"{nm}: history rows need numeric median")
            req(isinstance(row.get("hdi_89"), (list, tuple)) and len(row["hdi_89"]) == 2,
                f"{nm}: history rows need hdi_89 as [lo, hi]")
        if poll_engine:
            # v2 extras: share IS P(win); 89% bootstrap CI; honest flags
            req(isinstance(h.get("share"), (int, float)),
                f"{nm}: poll-matrix housemates need numeric share")
            ci = h.get("ci_89")
            req(isinstance(ci, (list, tuple)) and len(ci) == 2
                and all(isinstance(x, (int, float)) for x in ci),
                f"{nm}: ci_89 must be [lo, hi]")
            req(ci[0] <= ci[1], f"{nm}: ci_89 must be ordered [lo, hi]")
            mo = h.get("momentum")
            req(mo is None or isinstance(mo, (int, float)),
                f"{nm}: momentum must be null or numeric")
            req(isinstance(h.get("carried", False), bool),
                f"{nm}: carried must be boolean")

    actives = [h for h in hms if h["status"] == "active"]
    req(len(actives) >= 1, "at least one active housemate required")
    ssum = sum(h["p_rank_1"] for h in actives)
    req(abs(ssum - 1.0) < 0.01, f"active p_rank_1 must sum to 1 (got {ssum:.4f})")
    if poll_engine:
        shsum = sum(h["share"] for h in actives)
        req(abs(shsum - 1.0) < 0.01, f"active shares must sum to 1 (got {shsum:.4f})")

    gambit = [h["name"] for h in hms if h.get("gambit_flag") == 1]
    for h in hms:
        if h.get("gambit_flag") == 1:
            req(h["p_rank_1"] == 0.0,
                f"Gambit housemate {h['name']} must have p_rank_1 == 0 (zero-out rule)")
        # podium may contain gambit names only outside the winner slot
        if h.get("gambit_flag") in (1, True) and podium["winner"]["name"] == h["name"]:
            raise SchemaError(f"Gambit housemate {h['name']} cannot be projected winner")

    # --- at_risk (optional; shape follows the engine) -------------------------
    if "at_risk" in products and products["at_risk"]:
        if poll_engine:
            req(all(isinstance(a.get("share"), (int, float))
                    for a in products["at_risk"]),
                "poll-matrix at_risk entries must carry numeric share")
        else:
            hazards = [a.get("relative_hazard") for a in products["at_risk"]]
            req(all(isinstance(x, (int, float)) for x in hazards),
                "at_risk entries must carry numeric relative_hazard")

    # --- polls block (optional, auxiliary — P3.5, owner decision 2026-09-20) ---
    # Structure errors are hard failures; the anchor itself is diagnostic and
    # must never gate a certified run on its own.
    polls = products.get("polls")
    if polls:
        req(isinstance(polls, dict), "polls must be a dict when present")
        if polls.get("anchor_applied"):
            anchor = polls.get("anchor")
            req(isinstance(anchor, dict) and anchor.get("applied") is True,
                "polls.anchor_applied=true requires an applied anchor block")
            shifts = anchor.get("shifts", {})
            req(isinstance(shifts, dict) and
                all(isinstance(v, (int, float)) and math.isfinite(v)
                    for v in shifts.values()),
                "poll anchor shifts must be finite numbers")

    # --- engine block (v2): params recorded for every published number --------
    if poll_engine:
        engine = products.get("engine") or {}
        req(isinstance(engine.get("params"), dict) and engine["params"],
            "poll-matrix engine block must record its params")
        ds = products.get("data_sufficiency") or {}
        req(isinstance(ds.get("rows_in_window"), int) and ds["rows_in_window"] >= 1,
            "data_sufficiency.rows_in_window must be a positive integer")

    # --- optional-field consistency (only checked when present) ----------------
    if require_placeholder_consistency:
        if products.get("placeholder") is True:
            req(products["precision"] == "prior-predictive",
                "placeholder=true requires precision == prior-predictive")
    if "rhat_max" in products and products["rhat_max"] is not None:
        req(float(products["rhat_max"]) < 1.01,
            f"rhat_max {products['rhat_max']} >= 1.01 — rejected run must never be published")

    return warns


def validate_file(path: Path) -> list[str]:
    """Load + validate a predictions.json file. Raises SchemaError on failure."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    warns = validate_products(data)
    LOG.info("schema gate PASS: %s (%d housemates, precision=%s)",
             path, len(data.get("housemates", [])), data.get("precision"))
    return warns


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2:
        print("usage: python -m src.products_schema <predictions.json>", file=sys.stderr)
        raise SystemExit(2)
    try:
        warns = validate_file(Path(sys.argv[1]))
    except SchemaError as e:
        print(f"SCHEMA FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
    for w in warns:
        print(f"WARNING: {w}")
    raise SystemExit(0)
