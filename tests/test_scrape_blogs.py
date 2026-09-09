"""P3 tests — fixture-based, no network access ever."""
import json
from datetime import date
from pathlib import Path

import pytest

from src import scrape_blogs as sb

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- calendar

def test_week_window_anchored_to_premiere():
    season = {"premiere_date": "2026-07-26"}
    start, end = sb.week_window(season, 7)
    assert (start.isoformat(), end.isoformat()) == ("2026-09-06", "2026-09-13")


def test_current_week_mid_season():
    season = {"premiere_date": "2026-07-26"}
    assert sb.current_week(season, today=date(2026, 9, 9)) == 7


# ---------------------------------------------------------------- aliases + sentiment

def test_alias_matching_and_greedy_longest():
    hms = sb.load_housemates()
    idx = sb.build_alias_index(hms)
    hits = sb.match_housemates("Chimsom and Gerald both survived; Bluethophia too", idx)
    assert set(hits) >= {"Chimsom Chuka", "Gerard", "Bluethopia"}


def test_alias_covers_surnames():
    idx = sb.build_alias_index(sb.load_housemates())
    assert "Yusuf" in sb.match_housemates("Muhammed-Awal keeps the house guessing", idx)


def test_vader_bounds():
    assert -1.0 <= sb.vader_compound("I love this amazing show!") <= 1.0
    assert sb.vader_compound("I love this amazing show!") > 0
    assert sb.vader_compound("This is terrible and disappointing") < 0


# ---------------------------------------------------------------- parsing

def test_annotate_matches_and_flags_headline():
    idx = sb.build_alias_index(sb.load_housemates())
    items = [sb.new_item("test", "Abi wins Head of House", "u1", None, "Great week for Abi", 7),
             sb.new_item("test", "Lagos traffic report", "u2", None, "No housemates here", 7)]
    sb.annotate(items, idx)
    assert items[0]["housemates"] == ["Abi"]
    assert items[0]["headline_feature"] is True
    assert items[0]["sentiment"] is not None
    assert items[1]["housemates"] == []


def test_google_news_parse_from_fixture(monkeypatch):
    season = {"premiere_date": "2026-07-26"}
    rss_bytes = (FIXTURES / "sample_rss.xml").read_bytes()

    class FakeResp:
        status_code = 200
        content = rss_bytes

    monkeypatch.setattr(sb, "polite_get", lambda *a, **k: FakeResp())
    # single housemate query keeps the test fast and deterministic
    monkeypatch.setattr(sb, "load_housemates", lambda: [{"name": "Abi", "aliases": ["Abi"]}])
    items = sb.fetch_google_news(sb.make_session(), season, 7)
    urls = {i["url"] for i in items}
    assert "https://example.com/abi-hoh" in urls
    assert "https://example.com/roundup" in urls  # deduped set; unmatched quarantined later
    assert len(urls) == 3  # duplicate-free


def test_blog_listing_parse_and_quarantine(tmp_path, monkeypatch):
    html = (FIXTURES / "sample_listing.html").read_text()

    class FakeResp:
        status_code = 200
        content = html.encode()

    monkeypatch.setattr(sb, "polite_get", lambda *a, **k: FakeResp())
    monkeypatch.setattr(sb, "_month_archives_for_week", lambda w, s: ["https://fake/archive"])
    items = sb.scrape_bellanaija(sb.make_session(), {"premiere_date": "2026-07-26"}, 7)
    assert len(items) == 2
    idx = sb.build_alias_index(sb.load_housemates())
    sb.annotate(items, idx)
    matched = [i for i in items if i["housemates"]]
    quarantined = [i for i in items if not i["housemates"]]
    assert [i["title"] for i in matched] == ["Sultex speaks on life after BBNaija eviction"]
    assert [i["title"] for i in quarantined] == ["Ten Lagos restaurants worth the drive"]


def test_run_scrape_archives_and_quarantines(tmp_path, monkeypatch):
    season = {"premiere_date": "2026-07-26"}
    idx = sb.build_alias_index(sb.load_housemates())
    good = sb.new_item("test", "Ricky wins the arena game", "u1", None, "Ricky shines", 7)
    bad = sb.new_item("test", "Nigerian football roundup", "u2", None, "No housemates", 7)
    sb.annotate([good, bad], idx)

    monkeypatch.setattr(sb, "load_season", lambda: season)
    monkeypatch.setattr(sb, "SOURCES", {"test": lambda *a, **k: [good, bad]})

    summary = sb.run_scrape([7], sources=["test"], out_dir=tmp_path)
    assert summary["weeks"][7]["matched"] == 1
    assert summary["weeks"][7]["quarantined"] == 1

    week_dir = tmp_path / "week_07"
    matched_lines = (week_dir / "test.jsonl").read_text(encoding="utf-8").strip().splitlines()
    quarantined_lines = (week_dir / "quarantine.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(matched_lines[0])["housemates"] == ["Ricky"]
    assert json.loads(quarantined_lines[0])["title"] == "Nigerian football roundup"
    manifest = json.loads((week_dir / "manifest.json").read_text())
    assert manifest["sources"] == {"test": 2}


def test_dead_source_never_kills_the_run(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("layout changed")

    monkeypatch.setattr(sb, "load_season", lambda: {"premiere_date": "2026-07-26"})
    monkeypatch.setattr(sb, "SOURCES", {"dead": boom})
    summary = sb.run_scrape([7], sources=["dead"], out_dir=tmp_path)
    assert summary["weeks"][7]["sources"] == {"dead": 0}


# ---------------------------------------------------------------- manual notes

def test_manual_notes_loader(tmp_path):
    p = tmp_path / "manual_notes.csv"
    p.write_text("date,housemate,note_type,value,source_url,notes\n"
                 "2026-08-16,Neche,walk,exited_day_21,https://x,Wk3 walk-out\n")
    rows = sb.load_manual_notes(p)
    assert rows[0]["housemate"] == "Neche"
    assert rows[0]["note_type"] == "walk"
