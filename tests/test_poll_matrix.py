"""E1 tests — src/poll_matrix.py (fixture-based, no network)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import poll_matrix as pm  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _cfg():
    return pm.load_engine_config()


def _hm_ids():
    return {h["name"]: pm.housemate_id(h["name"])
            for h in pm.sb.load_housemates()}


def _snap(sources, week=9, captured="2026-09-26T19:00:00+00:00"):
    return {"week": week, "snapshot_type": "midweek", "captured_at": captured,
            "sources": sources, "anchor": {"applied": False}}


def _bb(entries, state="live"):
    return {"source": "bbnaijadaily", "type": "full-share", "state": state,
            "url": "https://bbnaijadaily.com/bbnaija-voting-polls/",
            "entries": entries, "quarantined": []}


def _ng(entries, state="ok"):
    return {"source": "ngnews247", "type": "rank-only", "state": state,
            "entries": entries, "quarantined": []}


def _manual(entries, state="ok"):
    return {"source": "manual", "type": "full-share", "state": state,
            "entries": entries, "quarantined": []}


def _tmp_log(log) -> Path:
    fd, p = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(log, fh)
    return Path(p)


# --------------------------------------------------------------------------- #
# unit-level: ids, config, gambit gate, actives
# --------------------------------------------------------------------------- #

def test_housemate_id_slug():
    assert pm.housemate_id("Temi Nkem") == "temi_nkem"
    assert pm.housemate_id("Chimsom Chuka") == "chimsom_chuka"
    assert pm.housemate_id("  Bells ") == "bells"


def test_load_engine_config_has_decided_values():
    cfg = pm.load_engine_config()
    assert cfg["cap"] == 5000
    assert cfg["lambda_decay"] == 0.6
    assert cfg["window_weeks"] == 3
    assert cfg["bootstrap_replicates"] == 1000
    assert cfg["interval_percent"] == 89          # owner override of Readme 95%
    assert cfg["grades"]["bbnaijadaily"] == 1.0
    assert cfg["grades"]["manual"] == 0.7
    assert cfg["grades"]["ngnews247"] == 0.5
    assert cfg["constraint_rules"]["mode"] == "soften_on_conflict"
    assert cfg["dedupe_rule"] == "latest_wins_per_source_week"


def test_gambit_gate_weeks_1_to_5_then_inert():
    # twist.json: Flora + Aikou, weeks 1-5; released effective week 6
    assert pm.load_gambit_names(1) == {"Flora", "Aikou"}
    assert pm.load_gambit_names(5) == {"Flora", "Aikou"}
    assert pm.load_gambit_names(6) == set()
    assert pm.load_gambit_names(9) == set()


def test_active_names_respect_exit_ledger():
    actives_w2 = pm.active_names(2)
    assert "Mercedes" not in actives_w2        # evicted wk2
    assert "Temi Nkem" in actives_w2
    actives_w4 = pm.active_names(4)
    assert "Cassi" not in actives_w4           # evicted wk4
    assert "Neche" not in actives_w4           # walked wk3
    assert "Nomy" in actives_w4                # DQ lands at wk7
    assert "Nomy" not in pm.active_names(8)


# --------------------------------------------------------------------------- #
# full-share row construction
# --------------------------------------------------------------------------- #

def test_full_share_row_renormalises_and_caps_sample():
    cfg = _cfg()
    entries = [{"name": "Keivo", "pct": 50.0, "votes": 400000},
               {"name": "Temi Nkem", "pct": 30.0, "votes": 240000},
               {"name": "Bells", "pct": 20.0, "votes": 160000}]
    rows = pm.rows_from_full_share_source(_bb(entries), 9, "snap1", cfg, set(),
                                          "https://x")
    assert len(rows) == 1
    r = rows[0]
    assert r["obs_type"] == "full_share"
    assert r["source_grade"] == 1.0
    ids = _hm_ids()
    assert r[ids["Keivo"]] == pytest.approx(0.5)
    assert r[ids["Temi Nkem"]] == pytest.approx(0.3)
    assert r[ids["Bells"]] == pytest.approx(0.2)
    assert r["sample_size"] == 5000            # 800k total votes -> capped
    assert r["provenance"] == "live_scrape"
    assert r["n_collapsed"] == 1


def test_full_share_row_missing_votes_uses_pseudo_n():
    cfg = _cfg()
    entries = [{"name": "Keivo", "pct": 60.0}, {"name": "Sheba", "pct": 40.0}]
    r = pm.rows_from_full_share_source(_bb(entries), 9, "s", cfg, set(), None)[0]
    assert r["sample_size"] == cfg["pseudo_n"]["full_share_missing_votes"]


def test_full_share_row_gambit_exclusion_renormalises():
    cfg = _cfg()
    entries = [{"name": "Flora", "pct": 40.0},
               {"name": "Aikou", "pct": 35.0},
               {"name": "Sheba", "pct": 25.0},
               {"name": "Bells", "pct": 25.0}]
    rows = pm.rows_from_full_share_source(_bb(entries), 2, "s", cfg,
                                          gambit={"Flora", "Aikou"}, url=None)
    ids = _hm_ids()
    assert len(rows) == 1
    r = rows[0]
    assert ids["Flora"] not in r and ids["Aikou"] not in r
    # renormalised over the 2 covered (non-Gambit) names only
    assert r[ids["Sheba"]] == pytest.approx(0.5)
    assert r[ids["Bells"]] == pytest.approx(0.5)
    assert r["active_set"] == ["Bells", "Sheba"]


def test_full_share_poll_of_only_gambit_members_dropped():
    # After exclusion fewer than 2 names remain covered -> Readme §3.1 drop.
    cfg = _cfg()
    entries = [{"name": "Flora", "pct": 55.0},
               {"name": "Aikou", "pct": 45.0}]
    rows = pm.rows_from_full_share_source(_bb(entries), 2, "s", cfg,
                                          gambit={"Flora", "Aikou"}, url=None)
    assert rows == []


def test_full_share_row_below_two_covered_dropped():
    cfg = _cfg()
    rows = pm.rows_from_full_share_source(_bb([{"name": "Keivo", "pct": 100.0}]),
                                          9, "s", cfg, set(), None)
    assert rows == []                    # Readme §3.1: <2 covered -> drop


def test_closed_or_dark_widget_yields_no_row():
    cfg = _cfg()
    entries = [{"name": "Keivo", "pct": 60.0}, {"name": "Sheba", "pct": 40.0}]
    for state in ("closed", "unreachable", "partial", "empty", "skipped"):
        assert pm.rows_from_full_share_source(_bb(entries, state=state),
                                              9, "s", cfg, set(), None) == []


# --------------------------------------------------------------------------- #
# ngnews constraint rows
# --------------------------------------------------------------------------- #

def test_ngnews_becomes_top_n_constraint_row_not_shares():
    cfg = _cfg()
    rows = pm.rows_from_ngnews(
        _ng([{"name": "Keivo", "rank": 1}, {"name": "Ricky", "rank": 2}]),
        9, "s", cfg)
    assert len(rows) == 1
    r = rows[0]
    assert r["obs_type"] == "top_N"
    assert r["source_grade"] == 0.5                 # grade C
    assert r["sample_size"] == 50                   # pseudo-n
    ids = _hm_ids()
    assert r[ids["Keivo"]] == 1 and r[ids["Ricky"]] == 1
    assert r["active_set"] == sorted(pm.active_names(9))


def test_ngnews_empty_or_unreachable_no_rows():
    cfg = _cfg()
    assert pm.rows_from_ngnews(_ng([], state="empty"), 9, "s", cfg) == []
    assert pm.rows_from_ngnews(_ng([], state="unreachable"), 9, "s", cfg) == []


# --------------------------------------------------------------------------- #
# seed rows from docs/polls.json (the real wk-8 row is the fixture)
# --------------------------------------------------------------------------- #

def test_seed_row_from_real_wk8_row():
    # docs/polls.json holds the wk-8 widget row (~621k total votes)
    cfg = _cfg()
    with open(pm.POLLS_LOG, encoding="utf-8") as fh:
        log = json.load(fh)
    assert [r for r in log["weeks"] if r.get("week") == 8], \
        "wk-8 seed row missing from docs/polls.json"
    gambit_by_week = {w: pm.load_gambit_names(w) for w in (1, 8, 9)}
    rows = pm.seed_rows_from_manual_log(cfg, gambit_by_week)
    wk8_rows = [r for r in rows if r["week"] == 8]
    assert len(wk8_rows) == 1
    r = wk8_rows[0]
    assert r["source_name"] == "bbnaijadaily-result-transcribed"
    assert r["source_grade"] == 1.0                  # decision #17: widget origin = A
    assert r["provenance"] == "transcribed_seed"
    assert r["sample_size"] == 5000                  # ~621k capped
    ids = _hm_ids()
    # Keivo 19.25% of the 99.99% logged total -> renormalised share
    assert r[ids["Keivo"]] == pytest.approx(0.1925 / 0.9999, rel=1e-4)
    hm_cols = [k for k in r if k not in pm.CORE_COLUMNS]
    assert len(hm_cols) == 11                        # all 11 nominated wk-8


def test_seed_fb_row_grade_b():
    cfg = _cfg()
    log = {"weeks": [{"week": 7, "recorded_at": "2026-09-15",
                      "source": "FB voting group (hand-logged)",
                      "poll": [{"name": "Sheba", "pct": 60.0},
                               {"name": "Oyin", "pct": 40.0}]}]}
    original = pm.POLLS_LOG
    try:
        pm.POLLS_LOG = _tmp_log(log)
        rows = pm.seed_rows_from_manual_log(cfg, {7: set()})
        assert len(rows) == 1
        assert rows[0]["source_name"] == "manual"
        assert rows[0]["source_grade"] == 0.7
        assert rows[0]["provenance"] == "manual_entry"
    finally:
        pm.POLLS_LOG = original


def test_seed_row_gambit_members_dropped_and_renormalised():
    cfg = _cfg()
    log = {"weeks": [{"week": 2, "recorded_at": "2026-08-05",
                      "source": "bbnaijadaily week-2 result image (transcribed)",
                      "poll": [{"name": "Flora", "pct": 40.0},
                               {"name": "Aikou", "pct": 35.0},
                               {"name": "Sheba", "pct": 25.0},
                               {"name": "Bells", "pct": 25.0}]}]}
    original = pm.POLLS_LOG
    try:
        pm.POLLS_LOG = _tmp_log(log)
        rows = pm.seed_rows_from_manual_log(cfg, {2: {"Flora", "Aikou"}})
        assert len(rows) == 1
        ids = _hm_ids()
        assert ids["Flora"] not in rows[0] and ids["Aikou"] not in rows[0]
        assert rows[0][ids["Sheba"]] == pytest.approx(0.5)
        assert rows[0][ids["Bells"]] == pytest.approx(0.5)
    finally:
        pm.POLLS_LOG = original


# --------------------------------------------------------------------------- #
# matrix assembly + latest-wins dedupe
# --------------------------------------------------------------------------- #

def test_build_matrix_latest_wins_dedupe(tmp_path, monkeypatch):
    cfg = _cfg()
    bb1 = _bb([{"name": "Keivo", "pct": 55.0}, {"name": "Sheba", "pct": 45.0}])
    bb2 = _bb([{"name": "Keivo", "pct": 60.0}, {"name": "Sheba", "pct": 40.0}])
    snap = _snap([bb1, bb2])
    monkeypatch.setattr(pm.sp, "load_snapshot", lambda w: snap)
    monkeypatch.setattr(pm, "POLLS_LOG", tmp_path / "no-log.json")
    rows = pm.build_matrix(9, cfg)
    bb_rows = [r for r in rows if r["source_name"] == "bbnaijadaily"]
    assert len(bb_rows) == 1                      # latest-wins
    assert bb_rows[0]["n_collapsed"] == 2
    ids = _hm_ids()
    assert bb_rows[0][ids["Keivo"]] == pytest.approx(0.60)   # the LATEST won


def test_build_matrix_seeds_plus_live(tmp_path, monkeypatch):
    cfg = _cfg()
    snap = _snap([_bb([{"name": "Keivo", "pct": 55.0}, {"name": "Sheba", "pct": 45.0}]),
                  _ng([{"name": "Keivo", "rank": 1}, {"name": "Ricky", "rank": 2}]),
                  _manual([{"name": "Keivo", "pct": 50.0}, {"name": "Oyin", "pct": 50.0}])])
    monkeypatch.setattr(pm.sp, "load_snapshot", lambda w: snap)
    monkeypatch.setattr(pm, "POLLS_LOG", tmp_path / "no-log.json")
    rows = pm.build_matrix(9, cfg)
    assert sorted(r["obs_type"] for r in rows) == ["full_share", "full_share", "top_N"]
    assert all(r["week"] == 9 for r in rows)


def test_build_matrix_no_snapshot_degrades_to_seeds(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(pm.sp, "load_snapshot", lambda w: None)
    rows = pm.build_matrix(9, cfg)   # real docs/polls.json: the wk-8 row exists
    assert rows, "seed rows expected from the real docs/polls.json"
    assert all(r["week"] == 8 for r in rows)


def test_gambit_gate_applies_in_build(tmp_path, monkeypatch):
    cfg = _cfg()
    entries = [{"name": "Flora", "pct": 40.0}, {"name": "Sheba", "pct": 35.0},
               {"name": "Bells", "pct": 25.0}]
    snap = _snap([_bb(entries)], week=2)
    monkeypatch.setattr(pm.sp, "load_snapshot", lambda w: snap if w == 2 else None)
    monkeypatch.setattr(pm, "POLLS_LOG", tmp_path / "no-log.json")
    monkeypatch.setattr(pm, "load_gambit_names",
                        lambda w: {"Flora", "Aikou"} if w <= 5 else set())
    rows = pm.build_matrix(2, cfg)
    assert len(rows) == 1
    ids = _hm_ids()
    assert ids["Flora"] not in rows[0] and ids["Aikou"] not in rows[0]
    assert rows[0][ids["Sheba"]] == pytest.approx(35.0 / 60.0)


# --------------------------------------------------------------------------- #
# CSV cache
# --------------------------------------------------------------------------- #

def test_csv_roundtrip(tmp_path):
    cfg = _cfg()
    entries = [{"name": "Keivo", "pct": 55.0}, {"name": "Sheba", "pct": 45.0}]
    rows = pm.rows_from_full_share_source(_bb(entries), 9, "s", cfg, set(), None)
    p = pm.matrix_to_csv(rows, tmp_path / "m.csv")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("obs_id,source_name,source_grade,obs_type")
    assert "keivo" in text and "sheba" in text
    assert "carried" in text
