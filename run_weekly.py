#!/usr/bin/env python
"""P6 — Weekly runner: the single Saturday entrypoint.

    python run_weekly.py [--lite] [--week N] [--prior-placeholder] [--skip-mcmc]

Flow (P6.1): scrape current week(s) -> manual overrides (already ingested by
preprocess) -> preprocess (gap-tolerant, backfill-bridge) -> MCMC -> products
-> SCHEMA GATE -> R-hat gate -> atomic write of data/predictions.json.

Gates in order (P6.3): schema validation, then the model's own R-hat gate.
A rejected run keeps the last good data/predictions.json and flags staleness —
never overwrites good output with bad.

The console review summary (P6.4) + per-stage timings (P6.5) end the run;
the human decides to `git push` (which fires the P8 deploy). Placeholder mode
exists only for deploy plumbing tests — it refuses to run on Saturdays so it
can never be mistaken for the real run (decision 2026-09-13).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import preprocess as pp  # noqa: E402
from src import scrape_blogs as sb  # noqa: E402
from src import score_week as sw  # noqa: E402
from src.products_schema import SchemaError, validate_products  # noqa: E402

LOG = logging.getLogger("run_weekly")

PREDICTIONS = ROOT / "data" / "predictions.json"
LAST_GOOD = ROOT / "data" / ".last_good_predictions.json"


def run_step(title: str, args: list[str], env: dict | None = None) -> None:
    """Run one pipeline stage as a subprocess with per-stage timing (P6.5)."""
    t0 = time.time()
    LOG.info("=== %s ===", title)
    merged = dict(os.environ)
    if env:
        merged.update(env)
    # Windows consoles default to cp1252 and logging crashes on non-Latin1
    # glyphs (e.g. the -> in renormalisation logs). UTF-8 everywhere, always.
    merged.setdefault("PYTHONUTF8", "1")
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run([sys.executable, *args], cwd=ROOT, env=merged)
    dt = time.time() - t0
    LOG.info("=== %s done in %.1fs (exit %d) ===", title, dt, proc.returncode)
    if proc.returncode != 0:
        raise RuntimeError(f"{title} failed (exit {proc.returncode})")
    return None


def cmd_scrape(weeks: list[int]) -> None:
    run_step("scrape", ["-m", "src.scrape_blogs", "--week", *[str(w) for w in weeks]])


def cmd_preprocess(weeks: list[int], scrape_missing: bool) -> None:
    args = ["-m", "src.preprocess", "--weeks", *[str(w) for w in weeks]]
    if scrape_missing:
        args.append("--scrape-missing")
    run_step("preprocess", args)


def cmd_model(lite: bool, prior_placeholder: bool) -> None:
    """Model stage. Weeks are calendar-true inside the model (config-driven).

    Default is the full spec tier (4 chains x 2000 draws); --lite is the
    explicitly-requested, honestly-labelled fallback. target_accept=0.95 is
    the value the P5 validation was certified with (2026-09-16) — overridable
    via BBN_TARGET_ACCEPT but never silently changed.
    """
    env = {
        "BBN_MCMC_CORES": os.environ.get("BBN_MCMC_CORES", "4"),
        "BBN_TARGET_ACCEPT": os.environ.get("BBN_TARGET_ACCEPT", "0.95"),
    }
    args = ["notebooks/bbnaija_mcmc.py"]
    if prior_placeholder:
        args.append("--prior-placeholder")
    elif lite:
        args.append("--lite")
    else:
        args.append("--full")
    args += ["--out", str(PREDICTIONS)]
    run_step("model", args, env=env)


def review_summary(products: dict, timings: dict[str, float]) -> None:
    """P6.4 console review — the human decides to push after reading this."""
    print("\n" + "=" * 64)
    print("WEEKLY RUN REVIEW — human decision required before push")
    print("=" * 64)
    pod = products.get("podium", {})
    for slot, label in (("winner", "Winner"),
                        ("runner_up", "Runner-up"),
                        ("second_runner_up", "2nd runner-up")):
        p = pod.get(slot, {})
        print(f"  {label:14s}: {p.get('name', '?'):20s} {p.get('prob', 0):.3f}")

    actives = [h for h in products.get("housemates", []) if h.get("status") == "active"]
    top = sorted(actives, key=lambda h: -h.get("p_rank_1", 0.0))[:6]
    print("\n  P(#1) leaders:")
    for h in top:
        tie = f"  (tie: {', '.join(h['statistical_tie_with'])})" if h.get("statistical_tie_with") else ""
        print(f"    {h['name']:20s} {h['p_rank_1']:.3f}{tie}")

    risks = products.get("at_risk", [])[:5]
    if risks:
        print("\n  At risk (relative hazard, nominated only):")
        for a in risks:
            print(f"    {a['name']:20s} x{a['relative_hazard']:.2f}")

    print("\n  Precision      :", products.get("precision"))
    print("  R-hat max      :", products.get("rhat_max"))
    print("  Model weights  :", products.get("model_weights"))
    print("  Divergences    :", products.get("divergences_by_candidate", "n/a"))
    print("  Missing weeks  :", products.get("missing_weeks", "n/a"))
    print("  Backfilled     :", products.get("backfilled_weeks", "n/a"))
    if products.get("placeholder"):
        print("  *** PLACEHOLDER (prior predictive) — NEVER PUBLISH AS PREDICTIONS ***")
    if products.get("gambit_banner"):
        print("  *** GAMBIT TWIST ACTIVE — flagged housemates: P(#1) = 0 ***")
    print("\n  Stage timings  :",
          ", ".join(f"{k} {v:.0f}s" for k, v in timings.items()) or "n/a")
    print("=" * 64)
    print("Next step (human): verify the numbers, then "
          "`git add docs/predictions.json && git commit && git push` to deploy.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="P6 weekly runner (single Saturday entrypoint)")
    ap.add_argument("--lite", action="store_true", help="reduced sampling (labelled 'lite', never silent)")
    ap.add_argument("--week", type=int, default=None,
                    help="force a specific season week (default: calendar-true current week)")
    ap.add_argument("--prior-placeholder", action="store_true",
                    help="deploy-plumbing mode: prior-predictive placeholder (refuses on Saturdays)")
    ap.add_argument("--skip-mcmc", action="store_true",
                    help="debug: skip scrape/preprocess/model; re-review the existing predictions.json")
    args = ap.parse_args(argv)

    t_all = time.time()
    timings: dict[str, float] = {}
    is_saturday = datetime.now(timezone.utc).weekday() == 5

    if args.prior_placeholder and is_saturday:
        LOG.error("--prior-placeholder refused on a Saturday (placeholder must never "
                  "become the weekly product). Run the real pipeline.")
        return 2

    try:
        if not args.skip_mcmc:
            if args.week:
                current = args.week
            else:
                season = sb.load_season()
                current = sb.current_week(season)
            # Scrape the current week; PREPROCESS the full season range —
            # build_all rewrites daily_cpi.json with only the requested weeks,
            # so a partial rebuild would silently drop earlier history
            # (caught 2026-09-16: weeks 1-5 vanished after a --weeks 6 7 run).
            # Rebuilding all weeks is idempotent: load_week_items dedupes by
            # (source, url) and the scraper appends deduped items.
            all_weeks = list(range(1, current + 1))
            LOG.info("pipeline: scrape wk%d, preprocess wks%s (lite=%s)",
                     current, all_weeks, args.lite)

            # P10.5 catch-up: score any pending eviction week against the
            # last-good archive BEFORE this run refreshes it. Best-effort —
            # a scoring problem must never block the certified run.
            t0 = time.time()
            try:
                for line in sw.score_pending_from_last_good():
                    LOG.info("score_previous: %s", line)
                timings["score_previous"] = time.time() - t0
            except Exception as e:  # noqa: BLE001 — scoring is never load-bearing
                LOG.warning("score_previous skipped: %s", e)
                timings["score_previous"] = time.time() - t0

            t0 = time.time()
            cmd_scrape([current])
            timings["scrape"] = time.time() - t0

            t0 = time.time()
            cmd_preprocess(all_weeks, scrape_missing=True)
            timings["preprocess"] = time.time() - t0

            t0 = time.time()
            cmd_model(args.lite, args.prior_placeholder)
            timings["model"] = time.time() - t0

        # ---- gates (P6.3): schema first, then R-hat gate already applied in-model ----
        t0 = time.time()
        with open(PREDICTIONS, encoding="utf-8") as fh:
            products = json.load(fh)
        warns = validate_products(products)
        timings["schema_gate"] = time.time() - t0
        for w in warns:
            LOG.warning("schema gate warning: %s", w)

        # Archive the validated product as last-good (refreshes every clean run,
        # so a future rejection restores the most recent good output, not an
        # ancient one). Kept out of git: it is host-local crash insurance.
        LAST_GOOD.write_bytes(PREDICTIONS.read_bytes())
        LOG.info("last-good archive refreshed: %s", LAST_GOOD.name)

        # Mirror into docs/ (git-tracked) — that copy is what the P8 deploy
        # validates and publishes; data/ stays out of git by convention.
        docs_pred = ROOT / "docs" / "predictions.json"
        docs_pred.write_bytes(PREDICTIONS.read_bytes())
        LOG.info("docs/predictions.json refreshed (commit + push to deploy)")

        review_summary(products, timings)
        LOG.info("total wall time: %.1fs", time.time() - t_all)
        return 0

    except (RuntimeError, SchemaError) as e:
        LOG.error("RUN REJECTED: %s", e)
        if LAST_GOOD.exists():
            shutil.copyfile(LAST_GOOD, PREDICTIONS)
            LOG.warning("last good predictions.json restored; staleness flag applies")
        else:
            LOG.warning("no last-good file exists yet — nothing restored")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
