"""BBNaija 2026 Predictor — E1 poll-matrix builder.

Owner decision 2026-09-22 (poll-matrix-engine-spec.md): the poll-matrix engine
replaces the MCMC engine. This module turns fan-poll observations into the
long-format matrix (Readme.txt §2 design, extended per spec §4) that
src/aggregate.py consumes. It never scrapes — raw snapshot files under
data/raw/week_XX/ and the hand-log docs/polls.json are the sources of truth;
this module only reads them (single-writer rule intact).

Schema (spec §4): one row per observation. Core columns:
  obs_id, source_name, source_grade, obs_type, sample_size, timestamp, week,
  active_set, poll_url, collection_method, snapshot_id, n_collapsed,
  provenance, carried
plus one column per canonical housemate id (lowercase, no spaces). Evicted
housemates keep their columns forever (NaN forward) so history stays intact.

Housemate-column semantics by obs_type (Readme §2.2, unchanged):
  full_share -> float share in [0, 1]
  bottom_N / top_N -> 0/1 flags
  rank -> int or NaN

Deltas decided by the owner (spec §12): latest-wins dedupe per (source, week)
with n_collapsed audit; transcribed finals enter as past-week full_share rows
(grade A, provenance=transcribed_seed — legitimate rolling-window history, NOT
outcome leakage: the leakage rule bars current-week finals from anchoring the
current week, per spec §8); Gambit housemates never enter the matrix while
their gambit period is active (spec §6, driven entirely by config/twist.json
gambit_periods — currently inert: Flora/Aikou were released in week 6).

The matrix is rebuilt idempotently on every run from the archived snapshots;
data/poll_matrix.csv is a derived cache, never a source.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from src import scrape_blogs as sb
from src import scrape_polls as sp

LOG = logging.getLogger("poll_matrix")

ROOT = Path(__file__).resolve().parent.parent
POLLS_LOG = ROOT / "docs" / "polls.json"
MATRIX_PATH = ROOT / "data" / "poll_matrix.csv"

CORE_COLUMNS = [
    "obs_id", "source_name", "source_grade", "obs_type", "sample_size",
    "timestamp", "week", "active_set", "poll_url", "collection_method",
    "snapshot_id", "n_collapsed", "provenance", "carried",
]

# sources in a snapshot that carry share data, mapped to their config identity
FULL_SHARE_SOURCES = {"bbnaijadaily", "manual", "bbnaijadaily-result-transcribed"}
RANK_ONLY_SOURCES = {"ngnews247"}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def load_engine_config() -> dict[str, Any]:
    with open(ROOT / "config" / "poll_engine.json", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Gambit gate (spec §6): active gambit members never enter the matrix
# --------------------------------------------------------------------------- #

def load_gambit_names(week: int) -> set[str]:
    """Canonical names of housemates whose gambit period covers `week`.

    Read ONLY from config/twist.json (never hardcoded). Empty set when the
    twist is inert for that week (current state: released effective wk 6).
    """
    with open(ROOT / "config" / "twist.json", encoding="utf-8") as fh:
        twist = json.load(fh)
    out: set[str] = set()
    for period in twist.get("gambit_periods", []):
        weeks = period.get("weeks", [])
        if weeks and weeks[0] <= week <= weeks[-1]:
            matched = sorted(set(sb.match_housemates(
                period.get("name", ""), sb.build_alias_index(sb.load_housemates()))))
            if len(matched) == 1:
                out.add(matched[0])
            else:
                LOG.warning("twist.json gambit name unresolved: %r", period.get("name"))
    return out


# --------------------------------------------------------------------------- #
# Housemate columns
# --------------------------------------------------------------------------- #

def housemate_id(name: str) -> str:
    """Canonical name -> column id: lowercase, no spaces (Readme §2.2)."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def active_names(week: int) -> list[str]:
    """Canonical names of housemates active in `week` (entered, not yet exited)."""
    out = []
    for h in sb.load_housemates():
        entry = int(h.get("entry_week", 1))
        exit_w = h.get("exit_week")
        if entry <= week and (exit_w is None or int(exit_w) > week):
            out.append(h["name"])
    return sorted(out)


# --------------------------------------------------------------------------- #
# Observation rows from one snapshot source
# --------------------------------------------------------------------------- #

def _obs_id(snapshot_id: str, source: str, week: int) -> str:
    raw = f"{snapshot_id}|{source}|{week}"
    return "obs_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _grade(source_name: str, cfg: dict[str, Any]) -> float:
    grades = cfg.get("grades", {})
    if source_name in grades:
        return float(grades[source_name])
    LOG.warning("no grade configured for source %r — defaulting to D (0.2)", source_name)
    return 0.2


def _pseudo_n(source_name: str, cfg: dict[str, Any]) -> int:
    return int(cfg.get("pseudo_n", {}).get(source_name,
                                           cfg.get("pseudo_n", {}).get(
                                               "full_share_missing_votes", 100)))


def rows_from_full_share_source(source: dict[str, Any], week: int, snapshot_id: str,
                                cfg: dict[str, Any], gambit: set[str],
                                url: str | None) -> list[dict[str, Any]]:
    """One full_share row per source snapshot (shares renormalised over the
    names the source covers — per Readme §3.3 the renormalisation over the
    row's covered set happens again inside aggregation)."""
    if source.get("state") not in ("live", "ok"):
        return []
    covered: dict[str, float] = {}
    for e in source.get("entries", []):
        nm = e.get("name")
        if not nm or e.get("pct") is None:
            continue
        if nm in gambit:
            continue  # spec §6: never enters the matrix
        covered[nm] = float(e["pct"]) / 100.0
    total = sum(covered.values())
    if total <= 0 or len(covered) < 2:          # Readme §3.1 drop rule
        return []
    covered = {k: v / total for k, v in covered.items()}

    # Readme §2.1: sample_size = actual votes = the poll's TOTAL, not one
    # housemate's count. Capped at `cap` in the weight formula (aggregation
    # side) AND here at storage time so the stored n is already effective-n.
    n_votes = sum(float(e["votes"]) for e in source.get("entries", [])
                  if e.get("votes"))
    sample_size = int(min(n_votes, cfg["cap"])) if n_votes else _pseudo_n(
        source.get("source", ""), cfg)

    name_to_id = {h["name"]: housemate_id(h["name"])
                  for h in sb.load_housemates()}
    prov = "transcribed_seed" if source.get("source") == "bbnaijadaily-result-transcribed" \
        else ("manual_entry" if source.get("source") == "manual" else "live_scrape")
    return [{
        "obs_id": _obs_id(snapshot_id, source.get("source", "?"), week),
        "source_name": source.get("source", "?"),
        "source_grade": _grade(source.get("source", "?"), cfg),
        "obs_type": "full_share",
        "sample_size": sample_size,
        "timestamp": snapshot_id,
        "week": week,
        "active_set": sorted(covered),
        "poll_url": url,
        "collection_method": ("manual_entry" if prov == "manual_entry" else "html_scrape"),
        "snapshot_id": snapshot_id,
        "n_collapsed": 1,
        "provenance": prov,
        "carried": False,
        **{name_to_id.get(nm, housemate_id(nm)): share
           for nm, share in covered.items()},
    }]


def rows_from_ngnews(source: dict[str, Any], week: int, snapshot_id: str,
                     cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """ngnews247 leaders -> ONE top_N=2 constraint row (spec §12 #21; grade C,
    pseudo-n 50; never shares). Empty when no leaders parsed."""
    if source.get("state") not in ("ok", "live"):
        return []
    leaders = [e["name"] for e in source.get("entries", []) if e.get("name")]
    if not leaders:
        return []
    name_to_id = {h["name"]: housemate_id(h["name"])
                  for h in sb.load_housemates()}
    row: dict[str, Any] = {
        "obs_id": _obs_id(snapshot_id, "ngnews247", week),
        "source_name": "ngnews247",
        "source_grade": _grade("ngnews247", cfg),
        "obs_type": "top_N",
        "sample_size": _pseudo_n("ngnews247", cfg),
        "timestamp": snapshot_id,
        "week": week,
        "active_set": sorted(active_names(week)),
        "poll_url": "https://www.youtube.com/@ngnews247",
        "collection_method": "api_free",
        "snapshot_id": snapshot_id,
        "n_collapsed": 1,
        "provenance": "live_scrape",
        "carried": False,
    }
    for nm in leaders:
        row[name_to_id.get(nm, housemate_id(nm))] = 1
    return [row]


# --------------------------------------------------------------------------- #
# Seed rows: transcribed finals from docs/polls.json (spec §11 / E5.1)
# --------------------------------------------------------------------------- #

def seed_rows_from_manual_log(cfg: dict[str, Any], gambit_by_week: dict[int, set[str]]
                              ) -> list[dict[str, Any]]:
    """    Hand-logged full-share rows (transcribed result images, live-window
    widget transcriptions, FB groups). Every docs/polls.json row with
    per-housemate pct values becomes one full_share matrix row.

    Grading keys on DATA ORIGIN (owner decision #17): rows whose source
    string identifies bbnaijadaily (transcribed result images AND live-window
    hand captures of the widget — both are the widget's numbers) are grade A;
    FB-group rows are grade B. Transcription risk is carried in provenance.
    These are past-week observations in a rolling window — legitimate
    history, never treated as current-week leakage."""
    if not POLLS_LOG.exists():
        return []
    with open(POLLS_LOG, encoding="utf-8") as fh:
        log = json.load(fh)
    name_to_id = {h["name"]: housemate_id(h["name"])
                  for h in sb.load_housemates()}
    out: list[dict[str, Any]] = []
    for row in log.get("weeks", []):
        week = int(row.get("week", -1))
        poll = row.get("poll") or []
        if week < 1 or not poll:
            continue
        src_is_widget = "bbnaijadaily" in (row.get("source", "") or "").lower()
        src_key = "bbnaijadaily-result-transcribed" if src_is_widget else "manual"
        gambit = gambit_by_week.get(week, set())
        covered: dict[str, float] = {}
        for p in poll:
            nm = p.get("name")
            if not nm or p.get("pct") is None or nm in gambit:
                continue
            covered[nm] = float(p["pct"]) / 100.0
        total = sum(covered.values())
        if total <= 0 or len(covered) < 2:
            continue
        covered = {k: v / total for k, v in covered.items()}
        votes = sum(float(p["votes"]) for p in poll if p.get("votes"))
        out.append({
            "obs_id": _obs_id(f"seed-w{week:02d}", src_key, week),
            "source_name": src_key,
            "source_grade": _grade(src_key, cfg),
            "obs_type": "full_share",
            "sample_size": int(min(votes, cfg["cap"])) if votes else _pseudo_n(src_key, cfg),
            "timestamp": row.get("recorded_at") or row.get("week_start") or f"seed-w{week}",
            "week": week,
            "active_set": sorted(covered),
            "poll_url": (row.get("source") or "")[:200] or None,
            "collection_method": "manual_entry",
            "snapshot_id": f"seed-w{week:02d}",
            "n_collapsed": 1,
            "provenance": "transcribed_seed" if src_is_widget else "manual_entry",
            "carried": False,
            **{name_to_id.get(nm, housemate_id(nm)): share
               for nm, share in covered.items()},
        })
    return out


# --------------------------------------------------------------------------- #
# Matrix assembly: latest-wins dedupe (owner decision #11)
# --------------------------------------------------------------------------- #

def build_matrix(week: int, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Rebuild the observation matrix from archived snapshots + manual log.

    Sources of truth (read-only): data/raw/week_XX/polls_snapshot.json for
    live weeks, docs/polls.json for seeds. Snapshots of one source within one
    week collapse into a single row — the LATEST captured_at wins, with
    n_collapsed recording how many were folded (owner decision #11)."""
    cfg = cfg or load_engine_config()

    # 1) seeds from the hand-log first
    gambit_by_week = {w: load_gambit_names(w)
                      for w in range(1, week + 1)}
    rows = seed_rows_from_manual_log(cfg, gambit_by_week)

    # 2) live snapshot for the current week
    snap = sp.load_snapshot(week)
    if snap is not None:
        snapshot_id = snap.get("captured_at", f"w{week:02d}")
        gambit = gambit_by_week.get(week, set())
        live_rows: list[dict[str, Any]] = []
        for source in snap.get("sources", []):
            src = source.get("source", "")
            if src in FULL_SHARE_SOURCES:
                live_rows.extend(rows_from_full_share_source(
                    source, week, snapshot_id, cfg, gambit, source.get("url")))
            elif src in RANK_ONLY_SOURCES:
                live_rows.extend(rows_from_ngnews(source, week, snapshot_id, cfg))
            else:
                LOG.debug("snapshot source %r not consumed by the matrix", src)

        # latest-wins per source_name (decision #11)
        by_source: dict[str, dict[str, Any]] = {}
        collapsed: dict[str, int] = {}
        for r in live_rows:
            k = r["source_name"]
            if k not in by_source or (r["timestamp"] or "") >= (by_source[k]["timestamp"] or ""):
                if k in by_source:
                    collapsed[k] = by_source[k].get("n_collapsed", 1) + 1
                by_source[k] = r
        for k, n in collapsed.items():
            by_source[k]["n_collapsed"] = n
            LOG.info("dedupe: %d same-week %s snapshot(s) collapsed (latest wins)",
                     n, k)
        rows.extend(by_source.values())
    else:
        LOG.warning("no polls snapshot for week %d — matrix runs on seeds only", week)

    LOG.info("matrix built: %d observation rows for weeks 1..%d "
             "(%d full_share, %d constraint)",
             len(rows), week,
             sum(1 for r in rows if r["obs_type"] == "full_share"),
             sum(1 for r in rows if r["obs_type"] != "full_share"))
    return rows


def matrix_to_csv(rows: list[dict[str, Any]], path: Path = MATRIX_PATH) -> Path:
    """Derived cache write (idempotent; data/ stays out of git by convention)."""
    hm_cols = sorted({k for r in rows
                      for k in r if k not in CORE_COLUMNS})
    cols = CORE_COLUMNS + hm_cols
    lines = [",".join(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            if v is None:
                cells.append("")
            elif isinstance(v, list):
                cells.append('"' + ";".join(v) + '"')
            elif isinstance(v, float):
                cells.append(f"{v:.6f}")
            else:
                s = str(v)
                cells.append('"' + s.replace('"', '""') + '"' if ('"' in s or "," in s) else s)
        lines.append(",".join(cells))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOG.info("matrix cache written: %s (%d rows x %d cols)", path.name, len(rows), len(cols))
    return path


def main(argv: list[str] | None = None) -> int:
    """Standalone rebuild: python -m src.poll_matrix [--week N]"""
    import argparse
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Rebuild data/poll_matrix.csv from archived snapshots")
    ap.add_argument("--week", type=int, default=None,
                    help="season week (default: calendar-true current week)")
    args = ap.parse_args(argv)
    week = args.week
    if week is None:
        season = sb.load_season()
        week = sb.current_week(season)
    cfg = load_engine_config()
    rows = build_matrix(week, cfg)
    matrix_to_csv(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
