#!/usr/bin/env python
"""E3 — Weekly runner: the single Saturday entrypoint (poll-matrix engine).

    python run_weekly.py [--week N] [--review-only]

Flow (E3.1): score_previous catch-up -> blog scrape (archive continuity only
— CPI is retired) -> poll fetch (the load-bearing input) -> poll-matrix build
-> aggregation/bootstrap -> SCHEMA GATE -> atomic write of data/predictions.json.

The MCMC/BMA stage is RETIRED from the path (owner decision 2026-09-22,
poll-matrix-engine-spec.md); its code stays in the repo untouched.

Gates: schema validation (products_schema.py). A rejected run keeps the last
good data/predictions.json and flags staleness — never overwrites good output
with bad. There is no R-hat gate anymore; the honesty signal is the review's
data-sufficiency block (rows in window, sources reporting, carried/unmeasured
flags) — the human reads it before pushing.
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

from src import scrape_blogs as sb  # noqa: E402  (season config + current_week)
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


def cmd_matrix(week: int) -> None:
    """E1 stage: rebuild the long-format poll matrix from archived snapshots
    + the manual log (idempotent, network-free)."""
    run_step("matrix", ["-m", "src.poll_matrix", "--week", str(week)])


def cmd_polls(week: int) -> None:
    """Poll fetch stage — now the LOAD-BEARING input (E3.1): the Saturday
    snapshot IS this week's primary observation. Still best-effort by
    contract (a fetch failure degrades the run to seeds-only with a loud
    review warning, never a rejected run)."""
    run_step("polls", ["-m", "src.scrape_polls", "--week", str(week)])


def cmd_aggregate(week: int) -> None:
    """E2 stage: weighted aggregation + softened constraints + bootstrap ->
    products (share=P(win), 89% CI, rank chips, podium)."""
    run_step("aggregate", ["-m", "src.aggregate", "--week", str(week),
                           "--out", str(PREDICTIONS)])


def review_summary(products: dict, timings: dict[str, float]) -> None:
    """E3.2 console review — the human decides to push after reading this."""
    print("\n" + "=" * 64)
    print("WEEKLY RUN REVIEW (poll-matrix engine) — human decision required")
    print("=" * 64)
    pod = products.get("podium", {})
    for slot, label in (("winner", "Winner"),
                        ("runner_up", "Runner-up"),
                        ("second_runner_up", "2nd runner-up")):
        p = pod.get(slot) or {}
        if p.get("name"):
            print(f"  {label:14s}: {p['name']:20s} {p.get('prob', 0):.3f}")

    actives = [h for h in products.get("housemates", []) if h.get("status") == "active"]
    print("\n  Standings (share = P(win), 89% bootstrap CI):")
    for h in sorted(actives, key=lambda x: -x.get("share", 0.0)):
        mo = h.get("momentum")
        mo_s = f"{mo:+.3f}" if isinstance(mo, (int, float)) else "  —  "
        flags = (" CARRIED" if h.get("carried") else "") \
            + (" UNMEASURED" if h.get("unmeasured") else "")
        tie = (f"  (tie: {', '.join(h['statistical_tie_with'])})"
               if h.get("statistical_tie_with") else "")
        print(f"    {h['name']:16s} S={h['share']:.4f} "
              f"[{h['ci_89'][0]:.3f},{h['ci_89'][1]:.3f}] "
              f"mom={mo_s} P1={h['p_rank_1']:.3f} P3={h['p_top3']:.3f}{flags}{tie}")

    risks = products.get("at_risk", [])[:5]
    if risks:
        print("\n  At risk (lowest share; bottom-N flagged marked *):")
        for a in risks:
            star = "*" if a.get("bottom_n_flag") else " "
            print(f"    {star}{a['name']:18s} {a['share']:.4f}")

    cons = (products.get("polls") or {}).get("constraint_log") or []
    if cons:
        print("\n  Constraints applied:")
        for c in cons:
            print(f"    {c.get('source')} {c.get('kind')}: "
                  f"{'agreed' if c.get('agreed') else 'CONFLICT-softened'} "
                  f"-> {c.get('after')}")

    ds = products.get("data_sufficiency", {})
    print("\n  Data sufficiency:")
    print(f"    rows in window : {ds.get('rows_in_window', 0)} "
          f"(full-share {ds.get('full_share_rows', 0)}, "
          f"constraint {ds.get('constraint_rows', 0)})")
    print(f"    sources        : {', '.join(ds.get('sources_reporting', [])) or 'NONE'}")
    print(f"    weeks          : {ds.get('weeks_in_window', [])}")
    polls = products.get("polls") or {}
    if polls.get("carried"):
        print(f"    carried        : {', '.join(polls['carried'])}")
    if polls.get("unmeasured_floored"):
        print(f"    unmeasured     : {', '.join(polls['unmeasured_floored'])} "
              "(floored at min measured share)")
    if ds.get("rows_in_window", 0) <= 2:
        print("    *** THIN WINDOW — CIs are wide and rankings fragile; "
              "read before pushing ***")
    print("\n  Engine         :", products.get("engine", {}).get("name", "?"))
    print("  Precision      :", products.get("precision"))
    print("\n  Stage timings  :",
          ", ".join(f"{k} {v:.0f}s" for k, v in timings.items()) or "n/a")
    print("=" * 64)
    print("Next step (human): verify the numbers, then "
          "`git add docs/predictions.json && git commit && git push` to deploy.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="E3 weekly runner (single Saturday entrypoint, poll-matrix engine)")
    ap.add_argument("--week", type=int, default=None,
                    help="force a specific season week (default: calendar-true current week)")
    ap.add_argument("--review-only", action="store_true",
                    help="skip scrape/aggregate; re-review the existing predictions.json")
    args = ap.parse_args(argv)

    t_all = time.time()
    timings: dict[str, float] = {}

    if args.review_only:
        LOG.info("--review-only: re-reviewing existing %s", PREDICTIONS)

    try:
        if not args.review_only:
            if args.week:
                current = args.week
            else:
                season = sb.load_season()
                current = sb.current_week(season)
            LOG.info("pipeline: polls wk%d -> matrix -> aggregate (poll-matrix engine)", current)

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

            # Blog scrape: ARCHIVE CONTINUITY ONLY (CPI is retired) — keeps
            # raw snapshots accruing for post-season review without feeding
            # anything. Never blocks the certified run.
            t0 = time.time()
            try:
                cmd_scrape([current])
            except Exception as e:  # noqa: BLE001
                LOG.warning("blog scrape skipped (%s) — archive-only stage", e)
            timings["scrape"] = time.time() - t0

            # Poll fetch: the load-bearing input. Best-effort by contract —
            # a failure degrades to seeds-only (review shows it loudly).
            t0 = time.time()
            try:
                cmd_polls(current)
            except Exception as e:  # noqa: BLE001 — degrade, never reject
                LOG.warning("poll fetch failed (%s) — running on seeds only", e)
            timings["polls"] = time.time() - t0

            t0 = time.time()
            cmd_matrix(current)
            timings["matrix"] = time.time() - t0

            t0 = time.time()
            cmd_aggregate(current)
            timings["aggregate"] = time.time() - t0

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
