"""P10.5 tracker auto-scoring — fixture-based tests (no network, no files
except tmp_path for the write path). Mirrors src/score_week.py's split:
pure scoring helpers are tested directly; orchestration on in-memory dicts.
"""

from __future__ import annotations

import json

import pytest

from src import score_week as sw


# --------------------------------------------------------------------------- #
# Fixtures: tiny predictions snapshot + roster + notes (self-contained)
# --------------------------------------------------------------------------- #

def make_roster() -> list[dict]:
    return [{"name": n, "aliases": [n]} for n in
            ("Alpha", "Beta", "Gamma", "Delta")]


ALIAS_INDEX = [
    ("alpha", "Alpha"), ("beta", "Beta"), ("gamma", "Gamma"), ("delta", "Delta"),
]


def make_predictions() -> dict:
    """Snapshot covers week 8. Nominated set: Alpha (hazard 2), Beta (1), Gamma (1)
    -> p_evict = 0.5 / 0.25 / 0.25. Winner: Alpha."""
    hist = lambda: [{"week": w, "median": 0.1} for w in range(1, 9)]
    return {
        "generated_at": "2026-09-20T06:58:19+00:00",
        "precision": "full",
        "podium": {"winner": {"name": "Alpha", "prob": 0.4}},
        "housemates": [
            {"name": "Alpha", "status": "active", "p_rank_1": 0.4, "history": hist()},
            {"name": "Beta", "status": "active", "p_rank_1": 0.3, "history": hist()},
            {"name": "Gamma", "status": "active", "p_rank_1": 0.2, "history": hist()},
            {"name": "Delta", "status": "evicted", "p_rank_1": 0.0,
             "history": [{"week": w, "median": 0.1} for w in range(1, 8)]},
        ],
        "at_risk": [
            {"name": "Alpha", "relative_hazard": 2.0, "nominated": True},
            {"name": "Beta", "relative_hazard": 1.0, "nominated": True},
            {"name": "Gamma", "relative_hazard": 1.0, "nominated": True},
        ],
    }


def make_notes() -> list[dict[str, str]]:
    return [
        {"date": "2026-09-20", "week": "8", "housemate": "Gamma",
         "note_type": "evicted", "value": "exited_day_56",
         "source_url": "https://x.test/g", "notes": ""},
        {"date": "2026-09-13", "week": "7", "housemate": "Delta",
         "note_type": "evicted", "value": "exited_day_49",
         "source_url": "https://x.test/d", "notes": ""},
    ]


def make_polls() -> dict:
    return {"weeks": [{"week": 8, "poll": [
        {"name": "Alpha", "pct": 10.0},
        {"name": "Beta", "pct": 5.0},
        {"name": "Gamma", "pct": 1.0},
    ]}]}


def make_track() -> dict:
    return {"method": "test", "weeks": [], "summary": None}


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def test_snapshot_week():
    assert sw.snapshot_week(make_predictions()) == 8
    assert sw.snapshot_week({"housemates": []}) == 0


def test_resolve_housemate_exact_alias_and_ambiguous():
    idx = [("ann", "Ann"), ("anna", "Anna")]
    assert sw.resolve_housemate("Gamma", ALIAS_INDEX) == "Gamma"
    assert sw.resolve_housemate("  gamma ", ALIAS_INDEX) == "Gamma"  # case/trim
    assert sw.resolve_housemate("Ann", idx) == "Ann"      # exact beats substring
    assert sw.resolve_housemate("An", idx) is None        # ambiguous -> human
    assert sw.resolve_housemate("", ALIAS_INDEX) is None
    assert sw.resolve_housemate("Zzz", ALIAS_INDEX) is None


def test_eviction_probs_normalize():
    probs = sw.eviction_probs(make_predictions()["at_risk"])
    assert probs == {"Alpha": 0.5, "Beta": 0.25, "Gamma": 0.25}
    assert abs(sum(probs.values()) - 1.0) < 1e-12


def test_eviction_probs_zero_total_raises():
    with pytest.raises(ValueError):
        sw.eviction_probs([{"name": "A", "relative_hazard": 0.0, "nominated": True}])


def test_brier_basic_and_empty():
    assert sw.brier([(0.5, 1), (0.5, 0)]) == 0.25
    assert sw.brier([(1.0, 1), (0.0, 0), (0.5, 1)]) == pytest.approx(1 / 12)
    with pytest.raises(ValueError):
        sw.brier([])


def test_poll_concordance_orders_and_ties():
    at_risk = [{"name": "A", "relative_hazard": 0.5, "nominated": True},
               {"name": "B", "relative_hazard": 1.0, "nominated": True},
               {"name": "C", "relative_hazard": 2.0, "nominated": True}]
    perfect = {"poll": [{"name": "A", "pct": 30}, {"name": "B", "pct": 20},
                        {"name": "C", "pct": 10}]}
    assert sw.poll_concordance(perfect, at_risk) == {"agree": 3, "pairs": 3,
                                                     "score": 1.0}
    inverted = {"poll": [{"name": "C", "pct": 40}, {"name": "A", "pct": 30},
                         {"name": "B", "pct": 20}]}
    assert sw.poll_concordance(inverted, at_risk)["score"] == 0.333  # 3-dp rounding
    ties = {"poll": [{"name": "A", "pct": 30}, {"name": "B", "pct": 10},
                     {"name": "C", "pct": 10}]}  # exact ties count as agreement
    assert sw.poll_concordance(ties, [{"name": n, "relative_hazard": h,
                                       "nominated": True}
                                      for n, h in (("A", 0.5), ("B", 1.0),
                                                   ("C", 1.0))])["agree"] == 3


# --------------------------------------------------------------------------- #
# Row building
# --------------------------------------------------------------------------- #

def test_score_week_row_winner_survives():
    exits, _ = sw.exits_for_week(make_notes(), 8, ALIAS_INDEX)
    row = sw.score_week_row(8, make_predictions(), exits,
                            make_polls()["weeks"][0], "2026-09-20T20:00:00+00:00")
    assert row["week"] == 8 and row["scored"] is True
    assert row["winner_survived"] is True
    assert row["predicted_winner"]["name"] == "Alpha"
    assert row["exits"] == [{"name": "Gamma", "type": "evicted", "day": 56,
                             "date": "2026-09-20", "source": "https://x.test/g"}]
    em = row["eviction_model"]
    assert em["top_hazard_pick"] == "Alpha"          # most at-risk stayed
    assert em["top_hazard_hit"] is False
    assert em["brier"] == pytest.approx(0.2917, abs=1e-4)
    assert [n["name"] for n in em["nominees"]] == ["Alpha", "Beta", "Gamma"]
    assert row["model_p_rank_1_top3"] == ["Alpha", "Beta", "Gamma"]  # Delta evicted
    assert row["poll_concordance"]["pairs"] == 3
    assert row["poll_concordance"]["score"] == 0.333  # 3-dp rounding


def test_score_week_row_winner_evicted_and_double_eviction():
    exits = [{"name": "Alpha", "type": "evicted", "day": 56, "date": "2026-09-20",
              "source": "s"},
             {"name": "Beta", "type": "evicted", "day": 56, "date": "2026-09-20",
              "source": "s"}]
    row = sw.score_week_row(8, make_predictions(), exits, None,
                            "2026-09-20T20:00:00+00:00")
    assert row["winner_survived"] is False            # the headline miss
    assert row["eviction_model"]["top_hazard_hit"] is True
    # y = [1, 1, 0] for [Alpha .5, Beta .25, Gamma .25] -> (0.25 + 0.5625 + 0.0625)/3
    assert row["eviction_model"]["brier"] == pytest.approx(0.2917, abs=1e-4)
    assert "poll_concordance" not in row              # no poll row -> omitted


# --------------------------------------------------------------------------- #
# Exit extraction
# --------------------------------------------------------------------------- #

def test_exits_for_week_filters_and_dedupes():
    rows = make_notes() + [
        # day-math fallback (no week column): day 56 -> week 8
        {"date": "2026-09-20", "week": "", "housemate": "Beta",
         "note_type": "walk", "value": "exited_day_56",
         "source_url": "https://x.test/b", "notes": ""},
        # duplicate Gamma row must not double-count
        {"date": "2026-09-20", "week": "8", "housemate": "Gamma",
         "note_type": "evicted", "value": "exited_day_56",
         "source_url": "https://x.test/g2", "notes": ""},
        # other week + nominations rows are not exits
        {"date": "2026-09-13", "week": "7", "housemate": "Alpha",
         "note_type": "evicted", "value": "exited_day_49",
         "source_url": "https://x.test/a", "notes": ""},
        {"date": "2026-08-23", "week": "5", "housemate": "",
         "note_type": "nominations", "value": "Alpha, Beta",
         "source_url": "https://x.test/n", "notes": ""},
    ]
    exits, unresolved = sw.exits_for_week(rows, 8, ALIAS_INDEX)
    assert unresolved == []
    assert {e["name"]: e["type"] for e in exits} == {"Gamma": "evicted",
                                                     "Beta": "walked"}
    assert len(exits) == 2


# --------------------------------------------------------------------------- #
# Orchestration (score_pending)
# --------------------------------------------------------------------------- #

def test_score_pending_scores_snapshot_week_and_tombstones_older():
    rows, track, lines, changed = sw.score_pending(make_predictions(), make_track(),
                                          make_notes(), make_polls(), ALIAS_INDEX)
    assert [r["week"] for r in rows] == [8]
    assert changed is True
    assert any("week 8 scored" in ln for ln in lines)
    # week 7 pending < snapshot 8 -> permanent tombstone, once
    tombs = [r for r in track["weeks"] if not r.get("scored")]
    assert len(tombs) == 1 and tombs[0]["week"] == 7
    assert "not retroactively scorable" in tombs[0]["reason"]

    sw.update_summary(track)
    assert track["summary"]["weeks_scored"] == 1
    assert track["summary"]["winner_survived_hits"] == 1
    assert track["summary"]["mean_brier"] == pytest.approx(0.2917, abs=1e-4)
    assert track["summary"]["mean_poll_concordance"] == 0.333

    # Idempotent: re-running with the same track appends nothing.
    rows2, track2, _, changed2 = sw.score_pending(make_predictions(), track,
                                                  make_notes(), make_polls(),
                                                  ALIAS_INDEX)
    assert rows2 == [] and changed2 is False
    assert len(track2["weeks"]) == 2


def test_score_pending_future_week_left_pending():
    notes = [{"date": "2026-09-27", "week": "9", "housemate": "Beta",
              "note_type": "evicted", "value": "exited_day_63",
              "source_url": "https://x.test/b9", "notes": ""}]
    rows, track, lines, changed = sw.score_pending(make_predictions(), make_track(),
                                          notes, None, ALIAS_INDEX)
    assert rows == [] and track["weeks"] == []
    assert changed is False
    assert any("left pending" in ln for ln in lines)


def test_score_pending_unresolved_name_blocks_scoring():
    notes = [{"date": "2026-09-20", "week": "8", "housemate": "Zzz",
              "note_type": "evicted", "value": "exited_day_56",
              "source_url": "https://x.test/z", "notes": ""}]
    rows, track, lines, changed = sw.score_pending(make_predictions(), make_track(),
                                          notes, None, ALIAS_INDEX)
    assert rows == [] and track["weeks"] == []
    assert changed is False
    assert any("unresolved housemate names" in ln for ln in lines)


def test_score_pending_no_exits_yet():
    rows, _, lines, changed = sw.score_pending(make_predictions(), make_track(),
                                      [], None, ALIAS_INDEX)
    assert rows == []
    assert changed is False
    assert any("no pending exit weeks" in ln for ln in lines)


def test_score_pending_explicit_week_targets_only_itself():
    # --week 7 with a week-8 snapshot: refused, and NO silent tombstone.
    rows, track, lines, changed = sw.score_pending(make_predictions(), make_track(),
                                          make_notes(), None, ALIAS_INDEX, week=7)
    assert rows == [] and track["weeks"] == []
    assert changed is False
    assert any("cannot be scored" in ln for ln in lines)


def test_score_pending_freshness_warning_on_post_hoc_snapshot():
    preds = make_predictions()
    preds["generated_at"] = "2026-09-21T06:58:19+00:00"  # day AFTER the exit
    rows, _, lines, changed = sw.score_pending(preds, make_track(), make_notes(), None,
                                      ALIAS_INDEX)
    assert rows, "scoring still proceeds"
    assert changed is True
    assert any("WARNING" in ln and "post-dates" in ln for ln in lines)


# --------------------------------------------------------------------------- #
# manual_notes.csv validator
# --------------------------------------------------------------------------- #

def test_validate_notes_clean():
    errors, warnings = sw.validate_notes(make_notes(), ALIAS_INDEX)
    assert errors == []
    assert warnings == []


def test_validate_notes_exit_row_errors():
    rows = [
        {"date": "20-09-2026", "week": "8", "housemate": "Zzz",
         "note_type": "evicted", "value": "exited_day_56", "source_url": "", "notes": ""},
        {"date": "2026-09-20", "week": "8", "housemate": "Gamma",
         "note_type": "rumor", "value": "gone", "source_url": "https://x.test", "notes": ""},
        {"date": "2026-09-20", "week": "", "housemate": "Beta",
         "note_type": "dq", "value": "bench incidents", "source_url": "", "notes": ""},
        {"date": "2026-09-20", "week": "8", "housemate": "Gamma",
         "note_type": "evicted", "value": "exited_day_56",
         "source_url": "https://x.test/g", "notes": ""},
        {"date": "2026-09-20", "week": "8", "housemate": "Gamma",
         "note_type": "evicted", "value": "exited_day_56",
         "source_url": "https://x.test/g", "notes": ""},
    ]
    errors, _ = sw.validate_notes(rows, ALIAS_INDEX)
    joined = "\n".join(errors)
    assert "bad date" in joined
    assert "does not resolve" in joined
    assert "unknown note_type" in joined
    assert "needs a week column or value=exited_day_N" in joined
    assert "source_url" in joined
    assert "duplicate exit row" in joined
    assert len(errors) >= 5


def test_validate_notes_nominations_rows():
    good_block = {"date": "2026-08-23", "week": "5", "housemate": "",
                  "note_type": "nominations",
                  "value": "Alpha, Beta, Gamma",
                  "source_url": "https://x.test/n", "notes": ""}
    errors, warnings = sw.validate_notes([good_block], ALIAS_INDEX)
    assert errors == [] and warnings == []

    empty_block = dict(good_block, week="1", value="")  # wk-1 Gambit election
    errors, _ = sw.validate_notes([empty_block], ALIAS_INDEX)
    assert errors == []

    typo = dict(good_block, value="Alpha, Gamna")
    errors, _ = sw.validate_notes([typo], ALIAS_INDEX)
    assert any("Gamna" in e and "matches no housemate" in e for e in errors)

    stray = dict(good_block, housemate="Alpha")
    _, warnings = sw.validate_notes([stray], ALIAS_INDEX)
    assert any("housemate value" in w for w in warnings)


def test_validate_notes_alias_rename_is_warning_not_error():
    rows = [{"date": "2026-09-20", "week": "8", "housemate": "gamma",
             "note_type": "evicted", "value": "exited_day_56",
             "source_url": "https://x.test/g", "notes": ""}]
    errors, warnings = sw.validate_notes(rows, ALIAS_INDEX)
    assert errors == []
    assert any("resolved to 'Gamma'" in w for w in warnings)


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #

def test_write_track_roundtrip(tmp_path):
    path = tmp_path / "track_record.json"
    track = make_track()
    track["weeks"].append(skip := sw.skip_row(7, "because", "t0"))
    sw.write_track(track, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["weeks"] == [skip]
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert not path.with_suffix(".json.tmp").exists()  # atomic replace cleaned up
