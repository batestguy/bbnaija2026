"""BBNaija 2026 Predictor — P4 preprocessing: raw archives → model-ready weekly table.

Produces `data/processed/daily_cpi.json`: a JSON array of housemate-week records
exactly per PLAN.md §5.1 (plus `backfilled`/`status` additions from the spec).

Key rules implemented here (non-negotiable per AGENTS.md):
  - CPI = 0.4*Comments + 0.3*Shares + 0.2*ArticleMentions + 0.1*HeadlineFeatures,
    each term min-max normalised across in-house housemates that week BEFORE
    weighting; weights RENORMALISE over available terms and the renormalisation
    is logged.
  - A missing week is never fabricated: no archive (+ failed bridge) → no records
    for that week and the week lands in every record's `missing_weeks`.
  - `gambit_flag` is weekly-varying, read only from config/twist.json.
  - `at_risk` comes from nomination facts (Wikipedia structured tables), so only
    nominated housemates are flagged; twists/immunity stay out of the model math.
  - Week numbers derive from config/season.json — runs never renumber weeks.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src import scrape_blogs as sb

LOG = logging.getLogger("preprocess")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
DAILY_CPI = PROCESSED_DIR / "daily_cpi.json"

BASE_WEIGHTS = {"comments": 0.4, "shares": 0.3, "article_mentions": 0.2, "headline_features": 0.1}
COUNT_TERMS = ("article_mentions", "headline_features")  # always computable from items
EXPOSED_TERMS = ("comments", "shares")                    # only if a source exposes counts


# --------------------------------------------------------------------------- #
# Loading + backfill bridge
# --------------------------------------------------------------------------- #

def load_week_items(raw_dir: Path, week: int) -> list[dict[str, Any]] | None:
    """All matched items archived for a week (None if the week has no archive).
    Deduped by (source, url) so re-scrapes never double-count."""
    week_dir = raw_dir / f"week_{week:02d}"
    if not week_dir.exists():
        return None
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(week_dir.glob("*.jsonl")):
        if path.name == "quarantine.jsonl":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            key = (item["source"], item["url"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def ensure_weeks(weeks: list[int], raw_dir: Path, scrape_missing: bool) -> tuple[list[int], list[int], list[int]]:
    """Backfill-bridge (P4.4): scrape any requested week that has no archive.
    Returns (available_weeks, still_missing_weeks, bridged_weeks). Bridge weeks
    are tagged `backfilled: true` downstream — never silently merged."""
    available, missing, bridged = [], [], []
    for week in weeks:
        if load_week_items(raw_dir, week) is not None:
            available.append(week)
            continue
        if scrape_missing:
            LOG.info("bridge: week %d has no archive — scraping it now (backfill)", week)
            sb.run_scrape([week], out_dir=raw_dir)
            if load_week_items(raw_dir, week) is not None:
                available.append(week)
                bridged.append(week)
                continue
        missing.append(week)
        LOG.warning("bridge: week %d unavailable (%s) — left missing, not fabricated",
                    week, "scrape failed" if scrape_missing else "scrape_missing disabled")
    return available, missing, bridged


# --------------------------------------------------------------------------- #
# Aggregation + CPI
# --------------------------------------------------------------------------- #

def in_house_weeks(hm: dict[str, Any], season: dict[str, Any]) -> list[int]:
    """Season weeks where the housemate was in the house (entry..exit inclusive;
    the exit week's Sunday closes their final week of engagement)."""
    last_week = sb.current_week(season)
    start = hm.get("entry_week", 1)
    end = hm["exit_week"] if hm.get("exit_week") else last_week
    return list(range(start, min(end, last_week) + 1))


def aggregate_housemates(items: list[dict[str, Any]], housemates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-housemate raw terms for one week from archived items."""
    agg: dict[str, dict[str, Any]] = {
        hm["name"]: {"article_mentions": 0, "headline_features": 0,
                     "comments": [], "shares": [], "sentiments": [], "urls": set()}
        for hm in housemates
    }
    for item in items:
        for name in item["housemates"]:
            if name not in agg:
                continue
            a = agg[name]
            a["article_mentions"] += 1
            a["headline_features"] += int(bool(item.get("headline_feature")))
            if item.get("sentiment") is not None:
                a["sentiments"].append(item["sentiment"])
            for term in EXPOSED_TERMS:
                if item.get(term) is not None:
                    a[term].append(item[term])
            a["urls"].add(item["url"])
    return agg


def minmax(values: dict[str, float]) -> dict[str, float]:
    """Min-max normalise across housemates; all-equal values → 0.0 (no signal)."""
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def compute_cpi(agg: dict[str, dict[str, Any]], names: list[str]) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Weekly CPI per housemate with the renormalisation rule. Returns
    (cpi, weights_used, available_terms). Renormalisation is logged."""
    raw: dict[str, dict[str, float | None]] = {n: {} for n in names}
    for term in COUNT_TERMS:
        for n in names:
            raw[n][term] = float(agg[n][term])
    for term in EXPOSED_TERMS:
        for n in names:
            vals = agg[n][term]
            raw[n][term] = (float(sum(vals)) if vals else None)

    available = [t for t in BASE_WEIGHTS if any(raw[n][t] is not None for n in names)]
    dropped = [t for t in BASE_WEIGHTS if t not in available]
    wsum = sum(BASE_WEIGHTS[t] for t in available)
    weights = {t: BASE_WEIGHTS[t] / wsum for t in available}
    if dropped:
        LOG.info("CPI renormalisation: sources exposed no %s this week — weights "
                 "renormalised over %s (weight mass %.2f → %.2f)",
                 dropped, available, wsum + sum(BASE_WEIGHTS[t] for t in dropped), wsum)

    cpi = {n: 0.0 for n in names}
    for term in available:
        vals = {n: raw[n][term] for n in names}
        norm = minmax({n: (v if v is not None else 0.0) for n, v in vals.items()})
        for n in names:
            cpi[n] += weights[term] * norm[n]
    return cpi, weights, available


# --------------------------------------------------------------------------- #
# Facts: AtRisk (Wikipedia nominations), Gambit (twist.json), status
# --------------------------------------------------------------------------- #

def nominated_names_for_week(wiki_items: list[dict[str, Any]], week: int,
                             alias_index: list[tuple[str, str]]) -> list[str] | None:
    """Extract the week's eviction block from the Wikipedia summary rows.
    'against_public_vote' is the true eviction block (verified against
    BellaNaija wk3 and Channels TV wk4); the 'nominated' row holds
    nomination-vote receivers, used only as a fallback. Returns None when no
    facts are available for the week."""
    for item in wiki_items:
        if item["source"] != "wikipedia":
            continue
        nom_map = item.get("extra", {}).get("nominations", {})
        idx = week - 1
        for key in ("against_public_vote", "nominated"):
            row = nom_map.get(key)
            if not row or idx >= len(row) or not row[idx].strip():
                continue
            return sb.match_housemates(row[idx], alias_index)
        if nom_map:
            LOG.warning("wikipedia: no nomination column for week %d in any summary row", week)
    return None


def nominations_overrides(rows: list[dict[str, str]],
                          alias_index: list[tuple[str, str]]) -> dict[int, list[str]]:
    """manual_notes.csv rows with note_type == 'nominations' pin a week's
    eviction block (used when structured sources lag, e.g. wiki weeks 5-6).
    An empty value pins an explicitly empty block (e.g. the week-1 Gambit
    election, when nobody was up for eviction)."""
    out: dict[int, list[str]] = {}
    for row in rows:
        if row.get("note_type", "").strip().lower() != "nominations":
            continue
        w = row.get("week", "").strip()
        if not w:
            continue
        out[int(w)] = sb.match_housemates(row.get("value", ""), alias_index)
    return out


def load_gambit_periods() -> tuple[dict[str, set[int]], int]:
    """(name → gambit weeks, twist_start_week). Both read only from twist.json."""
    with open(sb.CONFIG_DIR / "twist.json", encoding="utf-8") as fh:
        twist = json.load(fh)
    periods = {p["name"]: set(p["weeks"]) for p in twist.get("gambit_periods", [])}
    start = twist.get("twist_start_week")
    start = 1 if start is None else int(start)  # absent → no twist weeks (start beyond season)
    if twist.get("gambit_periods") and twist.get("twist_start_week") is None:
        start = min(min(w) for w in periods.values() if w)  # derive from earliest gambit week
    return periods, start


def load_season_safe() -> dict[str, Any]:
    return sb.load_season()


def exit_weeks_from_manual_notes(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """manual_notes.csv overrides: walk/dq/eviction rows pin exit week + type.
    Note types normalize to the status vocabulary (walk → walked, dq → disqualified).
    The explicit week column wins; exited_day_N day-math is the fallback."""
    status_map = {"walk": "walked", "dq": "disqualified",
                  "eviction_override": "evicted", "evicted": "evicted"}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        note_type = row.get("note_type", "").strip().lower()
        if note_type in ("walk", "dq", "eviction_override", "evicted"):
            week = None
            w = row.get("week", "").strip()
            if w:
                week = int(w)
            elif row.get("value", "").startswith("exited_day_"):
                day = int(row["value"].split("_")[-1])
                week = (day + 6) // 7  # ceil(day/7): day 14 → wk2, day 21 → wk3
            out[row["housemate"]] = {"exit_type": status_map[note_type], "exit_week": week,
                                     "week": week, "source": row.get("source_url", "")}
    return out


# --------------------------------------------------------------------------- #
# Record building
# --------------------------------------------------------------------------- #

def build_week_records(week: int, items: list[dict[str, Any]], season: dict[str, Any],
                       housemates: list[dict[str, Any]], alias_index: list[tuple[str, str]],
                       gambit_periods: dict[str, set[int]], twist_start_week: int,
                       manual_exits: dict[str, dict[str, Any]],
                       backfilled: bool,
                       nominations_override: dict[int, list[str]] | None = None) -> list[dict[str, Any]]:
    """Records for one week (items come from a bridged archive when backfilled)."""

    wiki_items = [i for i in items if i["source"] == "wikipedia"]
    blog_items = [i for i in items if i["source"] != "wikipedia"]
    nominated = (nominations_override or {}).get(week)
    if nominated is None:
        nominated = nominated_names_for_week(wiki_items, week, alias_index)
    if nominated is None:
        LOG.warning("week %d: no nomination facts — at_risk coded 0 for all (logged, not guessed)", week)
        nominated = []

    names = [hm["name"] for hm in housemates if week in in_house_weeks(hm, season)]
    agg = aggregate_housemates(blog_items, housemates)
    cpi, _weights, _available = compute_cpi(agg, names)
    sources_used = sorted({i["source"] for i in blog_items if i["housemates"]})

    week_start = sb.week_window(season, week)[0].isoformat()
    records: list[dict[str, Any]] = []
    for hm in housemates:
        name = hm["name"]
        if week not in in_house_weeks(hm, season):
            continue
        a = agg[name]
        # Week-relative status: in-house before exit week, exit_type ON the exit
        # week, and absent after (filtered by in_house_weeks). Config 'status'
        # is the household's CURRENT state — never copied into past weeks.
        exit_week = hm.get("exit_week")
        exit_type = hm.get("exit_type") or "evicted"
        if name in manual_exits:  # manual notes override config exit facts
            override = manual_exits[name]
            w = override.get("week")
            if w:
                exit_week = int(w)
            elif override["exit_week"]:
                exit_week = override["exit_week"]
            exit_type = override["exit_type"]
        if exit_week:
            status = "active" if week < exit_week else exit_type
        else:
            status = hm["status"]

        sentiments = a["sentiments"]
        record = {
            "season": season["season"],
            "week": week,
            "week_start": week_start,
            "housemate": name,
            "comments": (int(sum(a["comments"])) if a["comments"] else None),
            "shares": (int(sum(a["shares"])) if a["shares"] else None),
            "article_mentions": a["article_mentions"],
            "headline_features": a["headline_features"],
            "cpi": round(cpi[name], 6),
            "sentiment": round(sum(sentiments) / len(sentiments), 6) if sentiments else 0.0,
            "at_risk": int(name in nominated),
            "twist": int(week >= twist_start_week),
            "gambit_flag": int(week in gambit_periods.get(name, set())),
            "backfilled": backfilled,
            "status": status,
            "sources": sources_used,
            "missing_weeks": [],  # filled after all weeks are built
        }
        records.append(record)
    return records


def build_all(weeks: list[int], raw_dir: Path = RAW_DIR, scrape_missing: bool = False) -> dict[str, Any]:
    season = load_season_safe()
    housemates = sb.load_housemates()
    alias_index = sb.build_alias_index(housemates)
    gambit_periods, twist_start_week = load_gambit_periods()
    manual_exits = exit_weeks_from_manual_notes(sb.load_manual_notes())

    available, missing, bridged = ensure_weeks(weeks, raw_dir, scrape_missing)
    all_records: list[dict[str, Any]] = []
    per_week_summary: dict[int, dict[str, Any]] = {}
    notes_rows = sb.load_manual_notes()
    nom_overrides = nominations_overrides(notes_rows, alias_index)

    for week in sorted(available):
        items = load_week_items(raw_dir, week)
        records = build_week_records(week, items, season, housemates, alias_index,
                                     gambit_periods, twist_start_week, manual_exits,
                                     backfilled=week in bridged,
                                     nominations_override=nom_overrides)
        all_records.extend(records)
        per_week_summary[week] = {"records": len(records), "backfilled": week in bridged,
                                  "sources": sorted({i["source"] for i in items if i["source"] != "wikipedia"}),
                                  "nominated": sum(r["at_risk"] for r in records)}

    # per-housemate gap list (entry..last built week), excluding pre-entry/post-exit
    built_weeks = sorted(per_week_summary)
    for rec in all_records:
        hm = next(h for h in housemates if h["name"] == rec["housemate"])
        span_end = min(hm["exit_week"], max(built_weeks)) if hm.get("exit_week") else max(built_weeks)
        rec["missing_weeks"] = [w for w in range(hm.get("entry_week", 1), span_end + 1)
                                if w not in built_weeks]

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": season["season"],
        "weeks_built": built_weeks,
        "missing_weeks": sorted(missing),
        "records": all_records,
    }
    DAILY_CPI.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    LOG.info("daily_cpi.json written: %d records across weeks %s (missing: %s)",
             len(all_records), built_weeks, sorted(missing))
    return {"weeks_built": built_weeks, "missing_weeks": sorted(missing),
            "records": len(all_records), "per_week": per_week_summary}


# --------------------------------------------------------------------------- #
# CLI — backfill:  conda activate bap3 && python -m src.preprocess --weeks 1 2 3 4 5 6 7 --scrape-missing
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Build daily_cpi.json from raw archives")
    ap.add_argument("--weeks", type=int, nargs="*", default=None,
                    help="weeks to build (default: current week only)")
    ap.add_argument("--scrape-missing", action="store_true",
                    help="enable the backfill-bridge: scrape archived weeks that have no data yet")
    args = ap.parse_args(argv)

    season = load_season_safe()
    weeks = args.weeks or [sb.current_week(season)]
    summary = build_all(weeks, scrape_missing=args.scrape_missing)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
