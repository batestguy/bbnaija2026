"""predictions.json schema gate (P6.3 step 1 / P8.2).

One shared validator: the Saturday runner validates before writing, and the
deploy workflow validates before publishing — a bad file never goes live.

Relaxed-only rules: fields that existing P5 products already emit must stay
(extract/existing); required fields must be present, non-empty, and sane.
Anything stricter risks rejecting a spec-compliant assembly that carries
extra diagnostic fields.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)

PRECISION_OK = {"full", "lite", "prior-predictive"}
STATUS_OK = {"active", "evicted", "walked", "disqualified"}
SLOT_KEYS = ("winner", "runner_up", "second_runner_up")

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
    names = [podium[k].get("name") for k in SLOT_KEYS]
    req(all(isinstance(n, str) and n for n in names),
        f"podium slots must carry names, got {names}")
    req(len(set(names)) == 3, f"podium slots must be distinct people, got {names}")

    # --- housemates -----------------------------------------------------------
    hms = products["housemates"]
    req(isinstance(hms, list) and len(hms) >= 2,
        "housemates must be a list with at least 2 entries")
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

    actives = [h for h in hms if h["status"] == "active"]
    req(len(actives) >= 1, "at least one active housemate required")
    ssum = sum(h["p_rank_1"] for h in actives)
    req(abs(ssum - 1.0) < 0.01, f"active p_rank_1 must sum to 1 (got {ssum:.4f})")

    gambit = [h["name"] for h in hms if h.get("gambit_flag") == 1]
    for h in hms:
        if h.get("gambit_flag") == 1:
            req(h["p_rank_1"] == 0.0,
                f"Gambit housemate {h['name']} must have p_rank_1 == 0 (zero-out rule)")
        # podium may contain gambit names only outside the winner slot
        if h.get("gambit_flag") in (1, True) and podium["winner"]["name"] == h["name"]:
            raise SchemaError(f"Gambit housemate {h['name']} cannot be projected winner")

    # --- at_risk (optional) ----------------------------------------------------
    if "at_risk" in products and products["at_risk"]:
        hazards = [a.get("relative_hazard") for a in products["at_risk"]]
        req(all(isinstance(x, (int, float)) for x in hazards),
            "at_risk entries must carry numeric relative_hazard")

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
