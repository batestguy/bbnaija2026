#!/usr/bin/env python
"""P10.5 — Tracker auto-scoring + manual-notes validation.

    python src/score_week.py [--week N] [--check] [--validate-notes]

Scores published predictions against the actual Sunday exits so
docs/track_record.json stops being hand-scored (left-open item, 2026-09-17
handoff). Two invocation modes:

  1. Standalone, right after a Sunday eviction is logged in manual_notes.csv:
     `python src/score_week.py` — scores the newest pending week against the
     currently published docs/predictions.json snapshot.
  2. Catch-up stage inside run_weekly.py: `score_pending_from_last_good()`
     runs BEFORE the model stage, scoring pending weeks against
     data/.last_good_predictions.json (still the previous week's snapshot at
     that point) — after which Saturday's run overwrites the archive.

Write discipline (never violates the single-writer rule):
  - writes ONLY docs/track_record.json (never anything under data/);
  - track_record rows are append-only: an already-scored week is never
    re-scored or edited;
  - everything else is read-only (predictions, manual notes, polls).

Eviction model (documented in every row): within the nominated set the Cox
relative hazards are normalised to eviction probabilities
p_evict(h) = hazard(h) / sum(hazard over nominees); the Brier score is the
mean of (p − y)^2 over nominees with y = 1 for every exit that week (double
evictions each count). The headline hit/miss is simply whether the projected
final winner survived the week.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import scrape_blogs as sb  # noqa: E402

LOG = logging.getLogger("score_week")

DOCS = ROOT / "docs"
PREDICTIONS_PUBLISHED = DOCS / "predictions.json"
TRACK_RECORD = DOCS / "track_record.json"
POLLS = DOCS / "polls.json"
LAST_GOOD = ROOT / "data" / ".last_good_predictions.json"

EXIT_NOTE_TYPES = ("walk", "dq", "evicted", "eviction_override")
EXIT_TYPE_MAP = {"walk": "walked", "dq": "disqualified",
                 "eviction_override": "evicted", "evicted": "evicted"}


# --------------------------------------------------------------------------- #
# Pure scoring helpers (unit-tested; no IO)
# --------------------------------------------------------------------------- #

def snapshot_week(predictions: dict[str, Any]) -> int:
    """Season week a predictions snapshot covers = newest week in any history."""
    weeks = [pt["week"] for h in predictions.get("housemates", [])
             for pt in h.get("history", [])]
    return max(weeks) if weeks else 0


def resolve_housemate(raw: str, alias_index: list[tuple[str, str]]) -> str | None:
    """Canonical name for a manual-notes housemate field, or None.

    Exact canonical match wins; otherwise the alias substring match must be
    unambiguous (exactly one hit) — ambiguity is surfaced to the human, never
    silently resolved.
    """
    token = raw.strip()
    if not token:
        return None
    for alias, name in alias_index:
        if alias == token.lower():
            return name
    hits = sb.match_housemates(token, alias_index)
    return hits[0] if len(hits) == 1 else None


def exits_for_week(rows: list[dict[str, str]], week: int,
                   alias_index: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Exit rows for `week` → (resolved exits, unresolved raw names).

    Every exit type (evicted/dq/walk) counts: all three mean the housemate
    left the show that week (D11: mid-week DQ/walkout == eviction).
    """
    exits: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for row in rows:
        note_type = row.get("note_type", "").strip().lower()
        if note_type not in EXIT_NOTE_TYPES:
            continue
        w = row.get("week", "").strip()
        if w:
            if int(w) != week:
                continue
        elif row.get("value", "").startswith("exited_day_"):
            if (int(row["value"].split("_")[-1]) + 6) // 7 != week:
                continue
        else:
            continue
        canonical = resolve_housemate(row.get("housemate", ""), alias_index)
        if canonical is None:
            unresolved.append(row.get("housemate", ""))
            continue
        value = row.get("value", "")
        day = int(value.split("_")[-1]) if value.startswith("exited_day_") else None
        exits.append({"name": canonical, "type": EXIT_TYPE_MAP[note_type], "day": day,
                      "date": row.get("date", ""), "source": row.get("source_url", "")})
    # Stable, deduped by name (a duplicated CSV row must not double-count)
    seen: set[str] = set()
    unique = [e for e in exits if not (e["name"] in seen or seen.add(e["name"]))]
    return unique, unresolved


def eviction_probs(at_risk: list[dict[str, Any]]) -> dict[str, float]:
    """Nominated-set Cox hazards → eviction probabilities (sums to 1)."""
    nominated = [a for a in at_risk if a.get("nominated")]
    total = sum(float(a["relative_hazard"]) for a in nominated)
    if total <= 0:
        raise ValueError("nominated set has zero total hazard — cannot normalise")
    return {a["name"]: float(a["relative_hazard"]) / total for a in nominated}


def brier(pairs: list[tuple[float, int]]) -> float:
    """Mean of (p − y)^2 over (probability, outcome) pairs."""
    if not pairs:
        raise ValueError("no outcome pairs to score")
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def poll_concordance(poll: dict[str, Any], at_risk: list[dict[str, Any]]) -> dict[str, Any]:
    """Poll save-% order vs model hazard order, over the common housemates.

    A pair agrees when the poll's safer housemate (higher save-%) is also the
    model's safer one (lower hazard); exact ties count as agreement (they are
    orderings that do not disagree).
    """
    pct = {p["name"]: float(p["pct"]) for p in poll.get("poll", [])}
    haz = {a["name"]: float(a["relative_hazard"])
           for a in at_risk if a.get("nominated")}
    common = sorted(set(pct) & set(haz))
    agree = 0
    pairs = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            a, b = common[i], common[j]
            pairs += 1
            if (pct[a] >= pct[b]) == (haz[a] <= haz[b]):
                agree += 1
    return {"agree": agree, "pairs": pairs,
            "score": round(agree / pairs, 3) if pairs else None}


def score_week_row(week: int, predictions: dict[str, Any],
                   exits: list[dict[str, Any]],
                   poll_row: dict[str, Any] | None,
                   scored_at: str) -> dict[str, Any]:
    """Build one append-only track_record row (pure; caller handles IO)."""
    housemates = predictions.get("housemates", [])
    winner = predictions.get("podium", {}).get("winner", {})
    winner_name = winner.get("name")
    exit_names = {e["name"] for e in exits}

    probs = eviction_probs(predictions.get("at_risk", []))
    pairs = [(probs[n], 1 if n in exit_names else 0) for n in probs]
    top_hazard = max(probs, key=probs.get)

    active = [h for h in housemates if h.get("status") == "active"]
    top3 = [h["name"] for h in sorted(active, key=lambda h: -h.get("p_rank_1", 0.0))
            if h.get("p_rank_1", 0.0) > 0][:3]

    row: dict[str, Any] = {
        "week": week,
        "scored": True,
        "scored_at": scored_at,
        "predictions_generated_at": predictions.get("generated_at"),
        "precision": predictions.get("precision"),
        "predicted_winner": {"name": winner_name, "prob": winner.get("prob")},
        "winner_survived": winner_name not in exit_names if winner_name else None,
        "exits": exits,
        "eviction_model": {
            "method": "p_evict(h) = relative_hazard(h) / sum(hazard over nominees); "
                      "Brier = mean over nominees of (p - y)^2, y = 1 per exit "
                      "(double evictions each count).",
            "nominees": [{"name": n, "p_evict": round(probs[n], 4),
                          "exited": n in exit_names}
                         for n in sorted(probs, key=probs.get, reverse=True)],
            "brier": round(brier(pairs), 4),
            "top_hazard_pick": top_hazard,
            "top_hazard_hit": top_hazard in exit_names,
        },
        "model_p_rank_1_top3": top3,
    }
    if poll_row is not None:
        conc = poll_concordance(poll_row, predictions.get("at_risk", []))
        row["poll_concordance"] = {
            **conc,
            "poll_top3": [p["name"] for p in poll_row.get("poll", [])][:3],
            "note": "computed against the scored snapshot; may differ from "
                    "polls.json model_at_snapshot if predictions were regenerated",
        }
    return row


def skip_row(week: int, reason: str, scored_at: str) -> dict[str, Any]:
    """Append-only tombstone: records WHY a week is permanently unscorable."""
    return {"week": week, "scored": False, "reason": reason, "scored_at": scored_at}


# --------------------------------------------------------------------------- #
# Orchestration (IO lives here; pure logic above)
# --------------------------------------------------------------------------- #

def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def score_pending(predictions: dict[str, Any], track: dict[str, Any],
                  notes_rows: list[dict[str, str]], polls: dict[str, Any] | None,
                  alias_index: list[tuple[str, str]], week: int | None = None
                  ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], bool]:
    """Decide which weeks to score and append rows.

    Returns (scored_rows, track, log_lines, changed) — changed is True when
    ANY row (scored row or tombstone) was appended, i.e. the caller must
    persist. Selection: pending = exit weeks not yet in track_record. A
    pending week is scorable only against a snapshot covering exactly that
    week; older pending weeks get a permanent skip tombstone (no future
    snapshot can cover them); newer pending weeks are left for their own
    snapshot.
    """
    snap_w = snapshot_week(predictions)
    scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n_rows = len(track.get("weeks", []))  # delta at every return point = `changed`
    known = {r.get("week") for r in track.get("weeks", [])}
    pending = sorted({int(r["week"]) for r in notes_rows
                      if r.get("note_type", "").strip().lower() in EXIT_NOTE_TYPES
                      and (r.get("week", "").strip() or
                           r.get("value", "").startswith("exited_day_"))
                      } - known)
    lines: list[str] = []

    # Weeks OLDER than the snapshot can never be scored by any future snapshot
    # (coverage only moves forward) — record why, once, unless the operator
    # targeted a specific week.
    if week is None:
        for w in [x for x in pending if x < snap_w]:
            reason = (f"no published predictions snapshot predates this week's "
                      f"eviction (snapshot coverage starts at week {snap_w}); "
                      f"not retroactively scorable")
            track["weeks"].append(skip_row(w, reason, scored_at))
            lines.append(f"week {w} recorded as permanently unscorable: {reason}")

    target = week if week is not None else (max(pending) if pending else None)
    if target is None:
        lines.append(f"no pending exit weeks (snapshot covers week {snap_w})")
        return [], track, lines, len(track["weeks"]) > n_rows

    if target > snap_w:
        lines.append(f"week {target} exits exist but the published snapshot covers "
                     f"week {snap_w} — left pending for its own run")
        return [], track, lines, len(track["weeks"]) > n_rows

    if target < snap_w:
        lines.append(f"week {target} is older than the snapshot (week {snap_w}) "
                     f"and cannot be scored — use the default mode to tombstone it")
        return [], track, lines, len(track["weeks"]) > n_rows

    exits, unresolved = exits_for_week(notes_rows, target, alias_index)
    if unresolved:
        lines.append(f"week {target}: unresolved housemate names {unresolved} — "
                     f"fix manual_notes.csv and re-run; nothing scored")
        return [], track, lines, len(track["weeks"]) > n_rows
    if not exits:
        lines.append(f"no exit rows for week {target} in manual_notes.csv "
                     f"(add them after the Sunday show, then re-run)")
        return [], track, lines, len(track["weeks"]) > n_rows

    # Leakage guard: the snapshot must not be generated after the exit day.
    # Same-day generation is normal in the missed-Saturday workflow (run
    # Sunday 07:00, show Sunday 22:00); the day AFTER is definitely post-hoc.
    exit_date = datetime.fromisoformat(exits[0]["date"] or "9999-12-31").date()
    if datetime.fromisoformat(predictions["generated_at"]).date() > exit_date:
        lines.append(f"WARNING: snapshot generated {predictions['generated_at']} "
                     f"post-dates the exit date — verify it predates the eviction "
                     f"show before trusting this row")

    poll_row = None
    if polls:
        poll_row = next((p for p in polls.get("weeks", []) if p.get("week") == target), None)

    row = score_week_row(target, predictions, exits, poll_row, scored_at)
    track["weeks"].append(row)
    lines.append(f"week {target} scored: winner_survived={row['winner_survived']} "
                 f"brier={row['eviction_model']['brier']} "
                 f"top_hazard_hit={row['eviction_model']['top_hazard_hit']}")
    return [row], track, lines, True


def update_summary(track: dict[str, Any]) -> None:
    """Rolling summary recomputed from the full row list (idempotent)."""
    scored = [r for r in track.get("weeks", []) if r.get("scored")]
    briers = [r["eviction_model"]["brier"] for r in scored]
    concs = [r["poll_concordance"]["score"] for r in scored
             if r.get("poll_concordance", {}).get("score") is not None]
    track["summary"] = {
        "weeks_scored": len(scored),
        "winner_survived_hits": sum(1 for r in scored if r.get("winner_survived")),
        "mean_brier": round(sum(briers) / len(briers), 4) if briers else None,
        "mean_poll_concordance": (round(sum(concs) / len(concs), 3)
                                  if concs else None),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_track(track: dict[str, Any], path: Path = TRACK_RECORD) -> None:
    """Atomic write; JSON indent kept stable for diffable git history."""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(track, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)
    LOG.info("track record written: %s (%d week rows)", path,
             len(track.get("weeks", [])))


def score_pending_from_last_good() -> list[str]:
    """run_weekly.py catch-up entry: score pending weeks from the last-good
    archive BEFORE this run refreshes it. Failures raise; the caller isolates."""
    if not LAST_GOOD.exists():
        return ["no last-good archive yet — nothing to score"]
    predictions = _load_json(LAST_GOOD)
    track = _load_json(TRACK_RECORD) if TRACK_RECORD.exists() else {"weeks": []}
    polls = _load_json(POLLS) if POLLS.exists() else None
    alias_index = sb.build_alias_index(sb.load_housemates())
    rows, track, lines, changed = score_pending(predictions, track,
                                                sb.load_manual_notes(), polls,
                                                alias_index)
    if changed:
        update_summary(track)
        write_track(track)
    return lines


# --------------------------------------------------------------------------- #
# manual_notes.csv validator (the eviction-row pre-flight)
# --------------------------------------------------------------------------- #

VALID_NOTE_TYPES = set(EXIT_NOTE_TYPES) | {"nominations"}


def validate_notes(rows: list[dict[str, str]],
                   alias_index: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """manual_notes.csv pre-flight → (errors, warnings). Empty errors = clean."""
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for i, row in enumerate(rows, start=2):  # line 1 is the header
        where = f"row {i}"
        note_type = row.get("note_type", "").strip().lower()
        if note_type not in VALID_NOTE_TYPES:
            errors.append(f"{where}: unknown note_type '{note_type}' "
                          f"(valid: {sorted(VALID_NOTE_TYPES)})")
        raw_date = row.get("date", "").strip()
        try:
            datetime.strptime(raw_date, "%Y-%m-%d")
        except ValueError:
            errors.append(f"{where}: bad date '{raw_date}' (want YYYY-MM-DD)")
        week_raw = row.get("week", "").strip()
        if week_raw:
            try:
                if int(week_raw) < 1:
                    raise ValueError
            except ValueError:
                errors.append(f"{where}: bad week '{week_raw}'")

        if note_type in EXIT_NOTE_TYPES:
            raw_name = row.get("housemate", "").strip()
            canonical = resolve_housemate(raw_name, alias_index)
            if canonical is None:
                errors.append(f"{where}: housemate '{raw_name}' does not resolve "
                              f"to exactly one canonical name")
            elif canonical != raw_name:
                warnings.append(f"{where}: '{raw_name}' resolved to '{canonical}'")
            if not week_raw and not row.get("value", "").startswith("exited_day_"):
                errors.append(f"{where}: exit row needs a week column or "
                              f"value=exited_day_N")
            if not row.get("source_url", "").strip().startswith(("http://", "https://")):
                errors.append(f"{where}: exit row missing a source_url "
                              f"(auditability rule)")
            key = (week_raw, canonical or raw_name, note_type)
            if key in seen:
                errors.append(f"{where}: duplicate exit row {key}")
            seen.add(key)
        elif note_type == "nominations":
            if row.get("housemate", "").strip():
                warnings.append(f"{where}: nominations row has a housemate value "
                                f"(the block belongs in the value column)")
            if not week_raw:
                errors.append(f"{where}: nominations row missing week")
            for token in row.get("value", "").split(","):
                token = token.strip()
                if token and resolve_housemate(token, alias_index) is None:
                    errors.append(f"{where}: nomination token '{token}' matches no "
                                  f"housemate (typo would silently drop a nominee)")
    return errors, warnings


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="P10.5 tracker auto-scoring")
    ap.add_argument("--week", type=int, default=None,
                    help="score this week explicitly (default: newest pending)")
    ap.add_argument("--check", action="store_true",
                    help="dry run: print what would be scored, write nothing")
    ap.add_argument("--validate-notes", action="store_true",
                    help="pre-flight manual_notes.csv (exit code 1 on errors)")
    args = ap.parse_args(argv)

    if args.validate_notes:
        rows = sb.load_manual_notes()
        errors, warnings = validate_notes(rows, sb.build_alias_index(sb.load_housemates()))
        for e in errors:
            print(f"ERROR: {e}")
        for w in warnings:
            print(f"warn : {w}")
        print(f"\nmanual_notes.csv: {len(rows)} rows, {len(errors)} error(s), "
              f"{len(warnings)} warning(s) — "
              f"{'CLEAN' if not errors else 'FIX BEFORE THE RUN'}")
        return 1 if errors else 0

    predictions = _load_json(PREDICTIONS_PUBLISHED)
    track = _load_json(TRACK_RECORD) if TRACK_RECORD.exists() else {"weeks": []}
    polls = _load_json(POLLS) if POLLS.exists() else None
    alias_index = sb.build_alias_index(sb.load_housemates())
    rows, track, lines, changed = score_pending(predictions, track,
                                                sb.load_manual_notes(), polls,
                                                alias_index, week=args.week)
    for line in lines:
        print(line)
    if args.check:
        print("\n(dry run — nothing written)")
        return 0
    if changed:
        update_summary(track)
        write_track(track)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
