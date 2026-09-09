"""P4 tests — CPI renormalisation, AtRisk coding, weekly Gambit flags, bridge, gaps."""
import json
from pathlib import Path

import pytest

from src import preprocess as pp
from src import scrape_blogs as sb


def make_item(source, title, url, week, housemates, sentiment=0.1, headline=False, extra=None):
    it = sb.new_item(source, title, url, None, title, week)
    it["housemates"] = housemates
    it["sentiment"] = sentiment
    it["headline_feature"] = headline
    if extra:
        it["extra"] = extra
    return it


def wiki_item(week, nominated_row):
    return make_item("wikipedia", f"facts wk{week}", "https://en.wikipedia.org/wiki/S11", week,
                     [], extra={"nominations": {"nominated": nominated_row},
                                "exits": {}, "gambit_votes": {}})


SEASON = {"season": 11, "premiere_date": "2026-07-26"}


@pytest.fixture(scope="module")
def ctx():
    housemates = sb.load_housemates()
    return {
        "housemates": housemates,
        "alias_index": sb.build_alias_index(housemates),
        "gambit_periods": {"Flora": {1, 2, 3, 4, 5}, "Aikou": {1, 2, 3, 4, 5}},
        "twist_start": 1,
        "manual_exits": {},
    }


# ---------------------------------------------------------------- calendar + spans

def test_in_house_weeks_spans():
    season = {"premiere_date": "2026-07-26"}
    active = {"name": "X", "entry_week": 1, "exit_week": None}
    evicted = {"name": "Y", "entry_week": 1, "exit_week": 4}
    assert max(pp.in_house_weeks(active, season)) >= 7   # runs to the real current week
    assert pp.in_house_weeks(evicted, season) == [1, 2, 3, 4]


# ---------------------------------------------------------------- CPI

def test_minmax_all_equal_is_zero():
    assert pp.minmax({"a": 5, "b": 5, "c": 5}) == {"a": 0.0, "b": 0.0, "c": 0.0}
    m = pp.minmax({"a": 0, "b": 10})
    assert m == {"a": 0.0, "b": 1.0}


def test_cpi_renormalisation_logged_and_correct(caplog):
    names = ["Abi", "Bells"]
    agg = {n: {"article_mentions": 0, "headline_features": 0,
               "comments": [], "shares": [], "sentiments": [], "urls": set()} for n in names}
    agg["Abi"]["article_mentions"] = 10   # max
    agg["Bells"]["article_mentions"] = 0  # min
    agg["Abi"]["headline_features"] = 1
    with caplog.at_level("INFO", logger="preprocess"):
        cpi, weights, available = pp.compute_cpi(agg, names)
    assert available == ["article_mentions", "headline_features"]
    assert weights["article_mentions"] == pytest.approx(0.2 / 0.3)
    assert weights["headline_features"] == pytest.approx(0.1 / 0.3)
    assert cpi["Abi"] == pytest.approx(1.0) and cpi["Bells"] == pytest.approx(0.0)
    assert "renormalis" in caplog.text.lower()


# ---------------------------------------------------------------- facts

def test_nominated_names_for_week_maps_week_index(ctx):
    row = ["Abi | Aikou | Araga", "Bells | Flora | Oyin", "Ricky | Sheba | Tram"]
    wiki = [wiki_item(3, row)]
    nom = pp.nominated_names_for_week(wiki, 3, ctx["alias_index"])
    assert "Ricky" in nom and "Sheba" in nom and "Tram" in nom
    assert pp.nominated_names_for_week(wiki, 9, ctx["alias_index"]) is None
    assert pp.nominated_names_for_week([], 3, ctx["alias_index"]) is None


def test_exit_weeks_from_manual_notes_day_math():
    rows = [{"note_type": "walk", "value": "exited_day_21", "housemate": "Neche", "source_url": "u"}]
    out = pp.exit_weeks_from_manual_notes(rows)
    assert out["Neche"]["exit_week"] == 3 and out["Neche"]["exit_type"] == "walked"


def test_nominated_falls_back_to_against_public_vote(ctx):
    wiki = [wiki_item(5, {"nominated": ["a"] * 4 + [""],  # week 5 column empty
                           "against_public_vote": ["a"] * 4 + ["Oyin | Nomy | Yusuf"]})]
    wiki[0]["extra"]["nominations"] = {"nominated": ["a"] * 4 + [""],
                                       "against_public_vote": ["a"] * 4 + ["Oyin | Nomy | Yusuf"]}
    nom = pp.nominated_names_for_week(wiki, 5, ctx["alias_index"])
    assert set(nom) == {"Oyin", "Nomy", "Yusuf"}


def test_load_gambit_periods_from_config():
    periods, start = pp.load_gambit_periods()
    assert periods["Flora"] == {1, 2, 3, 4, 5} and periods["Aikou"] == {1, 2, 3, 4, 5}
    assert start == 1


# ---------------------------------------------------------------- week records

def test_build_week_records_gambit_and_atrisk(ctx):
    week = 3
    items = [
        make_item("googlenews-rss", "Flora shines in the arena", "u1", week, ["Flora"], 0.4, True),
        make_item("googlenews-rss", "Tram wins the wager task", "u2", week, ["Tram"], 0.6, False),
        make_item("googlenews-rss", "Barry and Keivo clash", "u3", week, ["Barry", "Keivo"], -0.3, False),
        wiki_item(week, ["a", "a", "Flora | Tram | Keivo"]),  # week 3 = index 2 (3rd column)
    ]
    records = pp.build_week_records(week, items, SEASON, ctx["housemates"], ctx["alias_index"],
                                    ctx["gambit_periods"], ctx["twist_start"], {}, backfilled=True)
    by_name = {r["housemate"]: r for r in records}
    assert by_name["Flora"]["gambit_flag"] == 1      # Gambit in week 3
    assert by_name["Aikou"]["gambit_flag"] == 1
    assert by_name["Tram"]["gambit_flag"] == 0
    assert by_name["Tram"]["at_risk"] == 1 and by_name["Keivo"]["at_risk"] == 1
    assert by_name["Flora"]["at_risk"] == 1
    assert by_name["Abi"]["at_risk"] == 0            # not in week-3 nomination column
    assert by_name["Tram"]["twist"] == 1
    assert all(r["backfilled"] for r in records)
    assert "googlenews-rss" in by_name["Flora"]["sources"]
    # Week-relative status: in week 3, only wk-3 exits (Kamsy evicted, Neche walked)
    # carry exit status; Mercedes/Martins (wk2) are already absent from records.
    assert "Mercedes" not in by_name and "Martins" not in by_name
    assert by_name["Kamsy"]["status"] == "evicted"
    assert by_name["Neche"]["status"] == "walked"
    assert by_name["Cassi"]["status"] == "active"  # in-house until her wk-4 exit
    assert by_name["Gerard"]["status"] == "active"  # in-house until her wk-6 exit


def test_build_week_records_gambit_released_after_week5(ctx):
    items = [make_item("googlenews-rss", "Flora speaks", "u1", 6, ["Flora"], 0.2, True),
             wiki_item(6, ["a", "a", "a", "a", "a", "Bells | Flora | Oyin"])]  # week 6 = index 5
    records = pp.build_week_records(6, items, SEASON, ctx["housemates"], ctx["alias_index"],
                                    ctx["gambit_periods"], ctx["twist_start"], {}, backfilled=False)
    by_name = {r["housemate"]: r for r in records}
    assert by_name["Flora"]["gambit_flag"] == 0      # released from week 6
    assert by_name["Flora"]["at_risk"] == 1


# ---------------------------------------------------------------- bridge + build_all

def test_ensure_weeks_reports_missing_without_fabricating(tmp_path):
    available, missing, bridged = pp.ensure_weeks([1, 2], tmp_path, scrape_missing=False)
    assert available == [] and missing == [1, 2] and bridged == []


def test_ensure_weeks_bridge_scrapes_and_tags(tmp_path, monkeypatch):
    def fake_scrape(weeks, out_dir=None, **kw):
        d = Path(out_dir) / f"week_{weeks[0]:02d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(sb, "run_scrape", fake_scrape)
    available, missing, bridged = pp.ensure_weeks([1], tmp_path, scrape_missing=True)
    assert available == [1] and missing == [] and bridged == [1]


def test_build_all_marks_gaps(tmp_path, monkeypatch, ctx):
    out_dir = tmp_path / "out"
    monkeypatch.setattr(pp, "PROCESSED_DIR", out_dir)
    monkeypatch.setattr(pp, "DAILY_CPI", out_dir / "daily_cpi.json")
    monkeypatch.setattr(pp, "load_season_safe", lambda: SEASON)
    monkeypatch.setattr(sb, "load_manual_notes", lambda: [])
    monkeypatch.setattr(pp, "exit_weeks_from_manual_notes", lambda rows: {})

    # only week 2 archived
    week_dir = tmp_path / "week_02"
    week_dir.mkdir()
    items = [make_item("googlenews-rss", "Abi leads the week", "u1", 2, ["Abi"], 0.3, True)]
    with (week_dir / "googlenews-rss.jsonl").open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

    summary = pp.build_all([1, 2], raw_dir=tmp_path, scrape_missing=False)
    assert summary["weeks_built"] == [2] and summary["missing_weeks"] == [1]
    payload = json.loads((out_dir / "daily_cpi.json").read_text(encoding="utf-8"))
    recs = {r["housemate"]: r for r in payload["records"] if r["week"] == 2}
    # active housemates carry the week-1 gap; Neche (walked wk3) is still in-house in wk2
    assert recs["Abi"]["missing_weeks"] == [1]
    assert recs["Cassi"]["missing_weeks"] == [1]
    assert recs["Abi"]["cpi"] >= recs["Neche"]["cpi"]  # Abi has the only mentions
    assert payload["season"] == 11
