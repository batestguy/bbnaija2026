"""P3.5 poll scraper tests — fixture-based, no network (repo convention).

Covers: TotalPoll closed/live/partial/empty states, ngnews247 RSS rank-only
parsing (newest-video-wins), backfill regexes (result articles are image-only
— never parsed for numbers), the median-of-sources anchor builder, and the
polls block of the products schema gate.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from src import scrape_blogs as sb
from src import scrape_polls as sp
from src.products_schema import SchemaError, validate_products

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Source 1: bbnaijadaily TotalPoll widget
# --------------------------------------------------------------------------- #

def test_parse_totalpoll_closed_state():
    """Closed widget (results embargoed) must yield NO entries — never guess."""
    out = sp.parse_totalpoll(_read("totalpoll_closed.html"))
    assert out["state"] == "closed"
    assert out["entries"] == []


def test_parse_totalpoll_live_entries():
    out = sp.parse_totalpoll(_read("totalpoll_live.html"))
    assert out["state"] == "live"
    by_name = {e["name"]: e for e in out["entries"]}
    # canonical alias matching, pct + votes extracted
    assert by_name["Keivo"]["pct"] == pytest.approx(19.25)
    assert by_name["Keivo"]["votes"] == 119589
    assert by_name["Chimsom Chuka"]["pct"] == pytest.approx(5.31)
    assert "Temi Nkem" in by_name
    # unmatched choice quarantined, not silently dropped
    assert any("Mystery Guest X" in q for q in out["quarantined"])
    assert all("Mystery" not in e["name"] for e in out["entries"])


def test_parse_totalpoll_partial_when_pct_missing():
    html = """
    <div id="totalpoll-poll-1" class="totalpoll-container">
      <div class="totalpoll-choice">
        <div class="totalpoll-choice-title">Keivo</div>
      </div>
    </div>"""
    out = sp.parse_totalpoll(html)
    assert out["state"] == "partial"          # name found, no share -> not 'live'


def test_parse_totalpoll_empty_on_garbage():
    assert sp.parse_totalpoll("<html><body>hello</body></html>")["state"] == "empty"


def test_reparse_live_archive_is_midweek_and_anchors(tmp_path):
    """Recovery path: a LIVE-state archived HTML rebuilds an anchorable snapshot."""
    html_path = tmp_path / "polls_bbnaijadaily.html"
    html_path.write_text(_read("totalpoll_live.html"), encoding="utf-8")
    snap = sp.reparse_snapshot(8, html_path)
    assert snap["snapshot_type"] == "midweek"
    assert snap["reparsed_from_archive"] is True
    assert snap["anchor"]["applied"] is True
    assert "bbnaijadaily" in snap["anchor"]["sources_used"]


def test_reparse_closed_archive_never_anchors(tmp_path):
    """A closed-state archive downgrades to snapshot_type='final', which the
    model refuses to anchor from (load_poll_anchor rule) — conservative by
    construction. (Week 1 has no manual rows; a week WITH manual rows could
    still anchor from manual data in the normal live path, but a closed-
    archive rebuild stays honest about not being a live-widget snapshot.)"""
    html_path = tmp_path / "polls_bbnaijadaily.html"
    html_path.write_text(_read("totalpoll_closed.html"), encoding="utf-8")
    snap = sp.reparse_snapshot(1, html_path)
    assert snap["snapshot_type"] == "final"   # honest downgrade
    assert snap["anchor"]["applied"] is False


# --------------------------------------------------------------------------- #
# Source 2: ngnews247 YouTube RSS (rank-only)
# --------------------------------------------------------------------------- #

def test_parse_ngnews_rss_newest_video_wins():
    alias_index = sb.build_alias_index(sb.load_housemates())
    out = sp.parse_ngnews_rss(_read("ngnews_rss.xml"), 8, alias_index)
    # newest week-8 title is the latest snapshot; the older one is stale
    assert [e["name"] for e in out["entries"]] == ["Keivo", "Ricky"]
    assert out["latest_video_published"] == "2026-09-18T18:00:00+00:00"


def test_parse_ngnews_rss_week_filter():
    alias_index = sb.build_alias_index(sb.load_housemates())
    out = sp.parse_ngnews_rss(_read("ngnews_rss.xml"), 7, alias_index)
    assert [e["name"] for e in out["entries"]] == ["Temi Nkem", "Keivo"]


def test_ngnews_weeks_discovery_regex():
    xml = _read("ngnews_rss.xml")
    weeks = {int(m) for m in re.findall(r"week\s*(\d+)\s+vote\s+poll", xml, re.IGNORECASE)}
    assert weeks == {7, 8}    # gambit video has no week number -> never confused


# --------------------------------------------------------------------------- #
# Backfill: past-week result articles are IMAGE-ONLY — archived, never parsed
# --------------------------------------------------------------------------- #

def test_result_article_discovery_and_image_regexes():
    html = _read("result_article.html")
    weeks = {int(m.group(1)) for m in sp.RESULT_LINK_RE.finditer(html)}
    assert weeks == {7, 6}
    img = sp.CONTENT_IMG_RE.search(html)
    assert img is not None
    assert "wp-content/uploads" in img.group(1)
    assert img.group(1).endswith(".jpeg")
    # and the fixture genuinely carries no percentages to scrape
    assert not re.search(r"\d{1,2}(?:\.\d+)?\s*%", html)


def test_backfill_anchor_never_applies():
    """A 'final' backfilled snapshot's anchor block must be inert by construction."""
    sources = [{"source": "bbnaijadaily", "type": "full-share", "state": "skipped",
                "entries": []},
               {"source": "bbnaijadaily-result-image", "type": "image",
                "state": "needs-transcription", "entries": []},
               {"source": "ngnews247", "type": "rank-only", "state": "ok", "entries": []}]
    anchor = sp.build_anchor(sources)
    assert anchor["applied"] is False
    assert anchor["shifts"] == {}
    assert anchor["sources_used"] == []


# --------------------------------------------------------------------------- #
# Anchor builder: median of full-share sources
# --------------------------------------------------------------------------- #

def _src(name: str, shares: dict[str, float], state: str = "live") -> dict:
    return {"source": name, "type": "full-share", "state": state,
            "entries": [{"name": k, "pct": v * 100} for k, v in shares.items()]}


def test_build_anchor_median_of_sources():
    sources = [
        _src("bbnaijadaily", {"Keivo": 0.60, "Temi Nkem": 0.40}),
        _src("manual", {"Keivo": 0.20, "Temi Nkem": 0.80}),
        {"source": "ngnews247", "type": "rank-only", "state": "ok", "entries": []},
    ]
    anchor = sp.build_anchor(sources)
    assert anchor["applied"] is True
    assert anchor["shares"]["Keivo"] == pytest.approx(0.40)
    assert anchor["shares"]["Temi Nkem"] == pytest.approx(0.60)
    n = 2
    assert anchor["shifts"]["Keivo"] == pytest.approx(
        sp.KAPPA * math.log(0.40 * n), abs=1e-6)
    assert "ngnews247" in anchor["sources_skipped"]


def test_build_anchor_uniform_poll_no_shift():
    anchor = sp.build_anchor([_src("bbnaijadaily", {"Keivo": 0.5, "Temi Nkem": 0.5})])
    assert anchor["applied"] is False
    assert anchor["shifts"]["Keivo"] == 0.0


def test_build_anchor_clip_on_extreme_share():
    shares = {"A": 0.50, **{f"H{i}": 0.05 for i in range(1, 11)}}   # 11 housemates
    anchor = sp.build_anchor([_src("bbnaijadaily", shares)])
    assert anchor["shifts"]["A"] == pytest.approx(sp.KAPPA * sp.ANCHOR_CLIP, abs=1e-6)


def test_build_anchor_missing_name_uses_available_median():
    sources = [
        _src("bbnaijadaily", {"Keivo": 0.7, "Temi Nkem": 0.3}),
        _src("manual", {"Keivo": 0.5, "Temi Nkem": 0.3, "Ricky": 0.2}),
    ]
    anchor = sp.build_anchor(sources)
    # Keivo: median(0.7, 0.5) = 0.6 ; Ricky: only one source has him
    assert anchor["shares"]["Keivo"] == pytest.approx(0.6)
    assert anchor["shares"]["Ricky"] == pytest.approx(0.2)


def test_build_anchor_no_full_share_sources():
    sources = [{"source": "ngnews247", "type": "rank-only", "state": "ok", "entries": []},
               {"source": "manual", "type": "full-share", "state": "empty", "entries": []}]
    anchor = sp.build_anchor(sources)
    assert anchor["applied"] is False
    assert anchor["shares"] == {}


# --------------------------------------------------------------------------- #
# Manual log source (repo file, static)
# --------------------------------------------------------------------------- #

def test_fetch_manual_week8_from_repo_log():
    out = sp.fetch_manual(8)
    assert out["state"] == "ok"
    assert len(out["entries"]) == 11
    assert {"Keivo", "Temi Nkem", "Chimsom Chuka"} <= {e["name"] for e in out["entries"]}


def test_fetch_manual_missing_week_empty():
    assert sp.fetch_manual(1)["state"] == "empty"


# --------------------------------------------------------------------------- #
# Products schema: polls block is optional but structure-checked
# --------------------------------------------------------------------------- #

def _base_products():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "test_products_schema", Path(__file__).resolve().parent / "test_products_schema.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.good_products()


def test_schema_polls_block_absent_ok():
    assert validate_products(_base_products()) == []


def test_schema_polls_anchor_applied_ok():
    p = _base_products()
    p["polls"] = {"week": 9, "anchor_applied": True,
                  "anchor": {"applied": True, "kappa": 0.25, "clip": 1.3863,
                             "shifts": {"A": 0.12, "B": -0.05}}}
    assert validate_products(p) == []


def test_schema_polls_anchor_mismatch_rejected():
    p = _base_products()
    p["polls"] = {"week": 9, "anchor_applied": True,
                  "anchor": {"applied": False, "shifts": {}}}
    with pytest.raises(SchemaError, match="applied"):
        validate_products(p)


def test_schema_polls_nonfinite_shift_rejected():
    p = _base_products()
    p["polls"] = {"week": 9, "anchor_applied": True,
                  "anchor": {"applied": True, "shifts": {"A": float("nan")}}}
    with pytest.raises(SchemaError, match="finite"):
        validate_products(p)
