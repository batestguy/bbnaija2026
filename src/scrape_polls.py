"""BBNaija 2026 Predictor — P3.5 multi-source fan-poll acquisition.

Owner decision 2026-09-20 (supersedes the 2026-09-18 track-only policy):
unofficial fan polls are SCRAPED weekly and feed a WEAK poll-anchored prior on
the housemate level. The count formula stays byte-for-byte frozen; the anchor
is a location shift m_i = kappa * clip(log(s_i * n), -clip, clip) on the
alpha-column offsets (s_i = poll share, n = number of anchored housemates),
so a uniform poll or a missing snapshot reproduces today's model exactly.

Sources, one isolated parser each (one layout change breaks one source, never
the run) — same rule as scrape_blogs.py:
  1. bbnaijadaily  — TotalPoll widget on /bbnaija-voting-polls/. SERVER-RENDERED
                     (verified 2026-09-20), so requests+BS4 suffice — no
                     headless browser. Full save-% shares. State-aware: the
                     widget goes dark after the Saturday 21:00 close ("Voting
                     is Closed ... collated by Deloitte"), which must yield
                     state='closed' — never fabricated numbers.
  2. ngnews247     — YouTube channel RSS. Poll results exist as video TITLES
                     ("... WEEK 8 VOTE POLL RESULT: KEIVO & RICKY ...").
                     RANK-ONLY signal (top leaders, no percentages): recorded
                     for concordance scoring, NEVER turned into shares.
  3. manual        — hand-logged rows in docs/polls.json (FB voting groups and
                     any source whose automated scrape failed).

Known, stated limitation (unchanged from the 2026-09-18 analysis): the two
automated sources share the same repeat-votable fan-war mechanics, so the
median-of-sources protects against ONE widget being stuffed, not against
shared bias. The manual channel stays the only human-moderated source.

Single-writer rule: this module runs only as a run_weekly.py stage or
manually — never on a schedule of its own.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

from src import scrape_blogs as sb

LOG = logging.getLogger("scrape_polls")

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
POLLS_LOG = DOCS_DIR / "polls.json"

# ---- anchor hyperparameters (weakly-informative; recorded in every snapshot,
# ---- printed to the run log, and copied into predictions.json priors block)
KAPPA = 0.25                    # shift = kappa * clipped log-share-vs-uniform
ANCHOR_CLIP = math.log(4.0)     # |log(s_i * n)| <= log(4): soft nudge, CPI stays dominant

BBNAIJADAILY_URL = "https://bbnaijadaily.com/bbnaija-voting-polls/"
NGNEWS_HANDLE = "ngnews24769"
CHANNEL_ID_CACHE = ROOT / "data" / "raw" / "ngnews_channel_id.txt"

CLOSED_MARKERS = ("voting is closed", "voting closed")

# Backfill: past-week result articles post the final chart as an IMAGE
# (verified 2026-09-20: wk-7 result article embeds a WhatsApp screenshot;
# zero percentages in HTML). We archive the image and mark the week
# 'needs-transcription' — a human reads it into the manual log. No OCR ever
# feeds the model silently.
# Real sidebar slugs: bbnaija-2026-week-9-vote-poll-result-and-eviction/
# (older posts may omit the season or the '-poll' part; keep both tolerated).
RESULT_LINK_RE = re.compile(
    r"bbnaija(?:-\d{4})?-week-(\d+)-vote(?:-poll)?-result[^\"']*")
CONTENT_IMG_RE = re.compile(
    r"<img[^>]*src=\"([^\"]*wp-content/uploads/[^\"]+)\"", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Source 1: bbnaijadaily TotalPoll widget (full shares)
# --------------------------------------------------------------------------- #

def parse_totalpoll(html: str) -> dict[str, Any]:
    """Parse a TotalPoll container out of the page HTML (pure, testable).

    Returns {state, entries, quarantined} where state is one of
    'live' | 'closed' | 'empty' | 'partial'. Never raises on layout drift —
    the raw HTML snapshot is archived so a parser fix can re-read history.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    if any(m in text for m in CLOSED_MARKERS):
        return {"state": "closed", "entries": [], "quarantined": []}

    container = soup.find(id=re.compile(r"totalpoll-poll-\d+")) or soup.find(
        class_="totalpoll-container")
    if container is None:
        return {"state": "empty", "entries": [], "quarantined": []}

    # Choice containers: every totalpoll-choice-* div that is not an inner
    # content/votes sub-block. Permissive on purpose — TotalPoll skins differ.
    choices = [c for c in container.find_all(class_=re.compile(r"totalpoll-choice"))
               if not any(k in " ".join(c.get("class", []))
                          for k in ("choice-content", "choice-results", "choice-votes",
                                    "choice-percentage", "choice-label", "choice-title"))]
    if not choices:
        return {"state": "empty", "entries": [], "quarantined": []}

    alias_index = sb.build_alias_index(sb.load_housemates())
    entries: list[dict[str, Any]] = []
    quarantined: list[str] = []
    for ch in choices:
        title_el = (ch.find(class_="totalpoll-choice-title")
                    or ch.find(class_="totalpoll-choice-label")
                    or ch.find(class_="choice-label")
                    or ch.find(["h2", "h3", "h4"]))
        name_text = title_el.get_text(" ", strip=True) if title_el else ""
        if not name_text:
            continue
        subtree = ch.get_text(" ", strip=True)
        pct_m = re.search(r"(\d+(?:\.\d+)?)\s*%", subtree)
        votes_m = re.search(r"([\d.,]+)\s*(?:k|K)?\s*votes", subtree)
        matched = sorted(set(sb.match_housemates(name_text, alias_index)))
        entry: dict[str, Any] = {"raw_name": name_text}
        if pct_m:
            entry["pct"] = float(pct_m.group(1))
        if votes_m:
            entry["votes"] = float(votes_m.group(1).replace(",", ""))
        if matched:
            if len(matched) > 1:
                quarantined.append(name_text)   # ambiguous label — human review
                continue
            entry["name"] = matched[0]
            entries.append(entry)
        else:
            quarantined.append(name_text)

    if not entries:
        return {"state": "partial", "entries": [], "quarantined": quarantined}
    if any("pct" not in e for e in entries):
        return {"state": "partial", "entries": entries, "quarantined": quarantined}
    return {"state": "live", "entries": entries, "quarantined": quarantined}


def fetch_bbnaijadaily(session: requests.Session, raw_dir: Path) -> dict[str, Any]:
    """Scrape the TotalPoll widget; archive the raw HTML next to the other raw
    snapshots so a parser fix can re-read history without re-scraping."""
    resp = sb.polite_get(session, BBNAIJADAILY_URL)
    if resp is None:
        return {"source": "bbnaijadaily", "type": "full-share", "state": "unreachable",
                "url": BBNAIJADAILY_URL, "entries": [], "quarantined": []}
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "polls_bbnaijadaily.html"
    raw_path.write_bytes(resp.content)
    parsed = parse_totalpoll(resp.text)
    return {"source": "bbnaijadaily", "type": "full-share", "state": parsed["state"],
            "url": BBNAIJADAILY_URL, "raw": raw_path.name, "entries": parsed["entries"],
            "quarantined": parsed["quarantined"]}


# --------------------------------------------------------------------------- #
# Source 2: ngnews247 YouTube RSS (rank-only leaders)
# --------------------------------------------------------------------------- #

TITLE_RE = re.compile(
    r"week\s*(\d+)\s+vote\s+poll\s+result\s*:\s*(.+?)(?:\s*\||$)", re.IGNORECASE)


def parse_ngnews_rss(xml_text: str, week: int,
                     alias_index: list[tuple[str, str]]) -> dict[str, Any]:
    """Extract rank-only leader names for `week` from a YouTube channel RSS.

    Gambit poll videos are a different question (immunity vote, not save
    vote) — recorded separately, never mixed into the save-poll anchor."""
    feed = feedparser.parse(xml_text)
    leaders: list[str] = []
    gambit_leaders: list[str] = []
    quarantined: list[str] = []
    latest: str | None = None
    week_seen = False
    for entry in feed.entries:
        title = getattr(entry, "title", "") or ""
        m = TITLE_RE.search(title)
        if not m or int(m.group(1)) != week:
            continue
        # Feed is newest-first: the newest week-W video IS the latest snapshot.
        # Older week-W titles are stale mid-week states — never merge them.
        if week_seen:
            continue
        week_seen = True
        names_raw = [p.strip() for p in re.split(r"\s*(?:&|and)\s*", m.group(2)) if p.strip()]
        is_gambit = "gambit" in title.lower()
        out = gambit_leaders if is_gambit else leaders
        for nm in names_raw:
            # dedupe: multiple aliases of the same housemate all match, and
            # that is NOT ambiguity — ambiguity is >1 DISTINCT canonical name
            matched = sorted(set(sb.match_housemates(nm, alias_index)))
            if len(matched) == 1:
                if matched[0] not in out:
                    out.append(matched[0])
                if latest is None:
                    latest = getattr(entry, "published", None)
            else:
                quarantined.append(nm)
    return {"state": "ok" if (leaders or gambit_leaders or quarantined) else "empty",
            "entries": [{"name": nm, "rank": i + 1} for i, nm in enumerate(leaders)],
            "gambit_leaders": gambit_leaders,
            "quarantined": quarantined, "latest_video_published": latest}


def resolve_channel_id(session: requests.Session) -> str | None:
    """Cached YouTube channel-id resolution for the @handle."""
    if CHANNEL_ID_CACHE.exists():
        cid = CHANNEL_ID_CACHE.read_text(encoding="utf-8").strip()
        if cid.startswith("UC"):
            return cid
    resp = sb.polite_get(session, f"https://www.youtube.com/@{NGNEWS_HANDLE}")
    if resp is None:
        return None
    m = re.search(r'"(?:channelId|externalId)":"(UC[^"]+)"', resp.text)
    if not m:
        return None
    CHANNEL_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHANNEL_ID_CACHE.write_text(m.group(1), encoding="utf-8")
    return m.group(1)


def fetch_ngnews247(session: requests.Session, week: int | None = None) -> dict[str, Any]:
    """Channel RSS grab — rank-only, so never a prior input (concordance only).
    week=None parses every week found in the feed (backfill mode) and returns
    {weeks: {week_number: parsed}} instead of one parsed dict."""
    cid = resolve_channel_id(session)
    if cid is None:
        base = {"source": "ngnews247", "type": "rank-only", "state": "unreachable",
                "entries": [], "quarantined": []}
        return {**base, "weeks": {}} if week is None else base
    resp = sb.polite_get(session,
                         f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
    if resp is None:
        base = {"source": "ngnews247", "type": "rank-only", "state": "unreachable",
                "entries": [], "quarantined": []}
        return {**base, "weeks": {}} if week is None else base
    alias_index = sb.build_alias_index(sb.load_housemates())
    if week is not None:
        parsed = parse_ngnews_rss(resp.text, week, alias_index)
        return {"source": "ngnews247", "type": "rank-only", **parsed}
    all_weeks: dict[int, dict[str, Any]] = {}
    for w in sorted({int(m) for m in
                     re.findall(r"week\s*(\d+)\s+vote\s+poll", resp.text, re.IGNORECASE)}):
        all_weeks[w] = parse_ngnews_rss(resp.text, w, alias_index)
    return {"source": "ngnews247", "type": "rank-only", "state": "ok",
            "entries": [], "quarantined": [], "weeks": all_weeks}


# --------------------------------------------------------------------------- #
# Backfill: past-week final results (rank-only now; images for human reading)
# --------------------------------------------------------------------------- #

def discover_result_articles(session: requests.Session) -> dict[int, str]:
    """week -> result-article URL, discovered from the polls page sidebar.
    Stops at the first page-level failure; partial coverage is fine."""
    resp = sb.polite_get(session, BBNAIJADAILY_URL)
    if resp is None:
        return {}
    out: dict[int, str] = {}
    for m in RESULT_LINK_RE.finditer(resp.text):
        w = int(m.group(1))
        url = m.group(0)
        if not url.startswith("http"):
            url = "https://bbnaijadaily.com/" + url.lstrip("/")
        out.setdefault(w, url)
    return out


def archive_result_image(session: requests.Session, article_url: str,
                         raw_dir: Path) -> dict[str, Any]:
    """Fetch one past-week result article; archive its content image (the
    final-results chart screenshot). Returns metadata for the snapshot row.
    NEVER parses numbers out of the image — transcription is a human step."""
    resp = sb.polite_get(session, article_url)
    if resp is None:
        return {"state": "unreachable", "entries": [], "quarantined": []}
    raw_dir.mkdir(parents=True, exist_ok=True)
    img_m = CONTENT_IMG_RE.search(resp.text)
    img_name = None
    if img_m:
        img_url = img_m.group(1).replace("&#038;", "&")
        img = sb.polite_get(session, img_url)
        if img is not None:
            img_name = "polls_result_image" + (
                ".jpg" if ".jp" in img_url.lower() else ".png")
            (raw_dir / img_name).write_bytes(img.content)
    return {"state": "needs-transcription" if img_name else "no-image",
            "entries": [], "quarantined": [],
            "article": article_url, "image": img_name}


# --------------------------------------------------------------------------- #
# Source 3: manual hand-log (docs/polls.json)
# --------------------------------------------------------------------------- #

def fetch_manual(week: int) -> dict[str, Any]:
    """Full-share rows logged by hand (FB groups etc.) for `week`."""
    if not POLLS_LOG.exists():
        return {"source": "manual", "type": "full-share", "state": "empty",
                "entries": [], "quarantined": []}
    with open(POLLS_LOG, encoding="utf-8") as fh:
        log = json.load(fh)
    entries: list[dict[str, Any]] = []
    quarantined: list[str] = []
    alias_index = sb.build_alias_index(sb.load_housemates())
    for row in log.get("weeks", []):
        if int(row.get("week", -1)) != week:
            continue
        for p in row.get("poll", []):
            matched = sorted(set(sb.match_housemates(p.get("name", ""), alias_index)))
            if len(matched) == 1 and p.get("pct") is not None:
                entries.append({"name": matched[0], "pct": float(p["pct"]),
                                "votes": p.get("votes")})
            else:
                quarantined.append(p.get("name", "<blank>"))
    return {"source": "manual", "type": "full-share",
            "state": "ok" if entries else "empty",
            "entries": entries, "quarantined": quarantined}


# --------------------------------------------------------------------------- #
# Anchor builder: median of full-share sources -> weak prior location shift
# --------------------------------------------------------------------------- #

def _normalized_shares(entries: list[dict[str, Any]]) -> dict[str, float]:
    """pct/100 renormalised within one source over the names it covers."""
    shares = {e["name"]: float(e["pct"]) / 100.0 for e in entries if "pct" in e}
    total = sum(shares.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in shares.items()}


def build_anchor(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Median-of-sources anchor. Rank-only and unreachable sources are logged
    but NEVER contribute shares (a 2-name leaderboard can't become a share
    without fabricating the rest). Returns the snapshot's anchor block."""
    full = [s for s in sources if s.get("type") == "full-share"
            and s.get("state") in ("live", "ok")]
    per_source = [_normalized_shares(s["entries"]) for s in full]
    per_source = [d for d in per_source if d]
    names = sorted({n for d in per_source for n in d})

    shares: dict[str, float] = {}
    shifts: dict[str, float] = {}
    if per_source and names:
        n_anchored = len(names)
        for nm in names:
            vals = [d[nm] for d in per_source if nm in d]
            s_i = statistics.median(vals)
            shares[nm] = round(s_i, 6)
            log_rel = math.log(s_i * n_anchored)          # 0 when exactly uniform
            shifts[nm] = round(KAPPA * max(-ANCHOR_CLIP, min(ANCHOR_CLIP, log_rel)), 6)
    applied = any(abs(v) > 1e-9 for v in shifts.values())
    skipped = [s.get("source") for s in sources
               if s.get("type") != "full-share" or s.get("state") not in ("live", "ok")]
    return {
        "applied": applied,
        "method": "median-of-full-share-sources",
        "kappa": KAPPA,
        "clip": round(ANCHOR_CLIP, 6),
        "shares": shares,
        "shifts": shifts,
        "sources_used": [s.get("source") for s in full],
        "sources_skipped": skipped,
        "note": ("uniform/missing poll -> all shifts 0 -> model identical to "
                 "no-anchor (gap-tolerant guarantee)") if not applied else
                ("weak alpha-column location shift; count formula unchanged"),
    }


# --------------------------------------------------------------------------- #
# Orchestration + persistence
# --------------------------------------------------------------------------- #

def collect_snapshot(week: int, live: bool = True) -> dict[str, Any]:
    """Scrape every source and assemble the week's snapshot dict.
    snapshot_type: 'midweek' = live grab during the Saturday run window (the
    only type the prior anchor may consume); 'final' = backfilled post-close."""
    session = sb.make_session()
    raw_dir = ROOT / "data" / "raw" / f"week_{week:02d}"
    sources: list[dict[str, Any]] = []
    if live:
        sources.append(fetch_bbnaijadaily(session, raw_dir))
        sources.append(fetch_ngnews247(session, week))
    else:
        sources.append({"source": "bbnaijadaily", "type": "full-share",
                        "state": "skipped", "entries": [], "quarantined": []})
        sources.append({"source": "ngnews247", "type": "rank-only",
                        "state": "skipped", "entries": [], "quarantined": []})
    sources.append(fetch_manual(week))

    for s in sources:
        if s.get("quarantined"):
            LOG.warning("polls[%s]: quarantined unmatched labels: %s",
                        s.get("source"), s["quarantined"])
    anchor = build_anchor(sources)
    return {"week": week,
            "snapshot_type": "midweek" if live else "final",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "sources": sources, "anchor": anchor}


def reparse_snapshot(week: int, html_path: Path) -> dict[str, Any]:
    """Offline recovery: re-parse an ARCHIVED polls_bbnaijadaily.html (captured
    during the live window) with the current parser and rebuild the week's
    snapshot without any network. Use after fixing parse_totalpoll against a
    live-DOM drift. snapshot_type stays honest: 'midweek' only when the
    archived widget state is 'live'; a closed-state archive can never anchor."""
    parsed = parse_totalpoll(html_path.read_text(encoding="utf-8"))
    bb = {"source": "bbnaijadaily", "type": "full-share", "state": parsed["state"],
          "url": BBNAIJADAILY_URL, "raw": html_path.name,
          "entries": parsed["entries"], "quarantined": parsed["quarantined"],
          "reparsed": True}
    sources = [bb,
               {"source": "ngnews247", "type": "rank-only", "state": "skipped",
                "entries": [], "quarantined": []},
               fetch_manual(week)]
    for s in sources:
        if s.get("quarantined"):
            LOG.warning("reparse wk%d polls[%s]: quarantined %s",
                        week, s.get("source"), s["quarantined"])
    return {"week": week,
            "snapshot_type": "midweek" if parsed["state"] == "live" else "final",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "reparsed_from_archive": True,
            "sources": sources, "anchor": build_anchor(sources)}


def backfill(up_to_week: int) -> None:
    """Recover what is recoverable for weeks 1..up_to_week-1 and archive it:
      - ngnews247 rank-only leaders per week (clean, automatic);
      - bbnaijadaily result-article images per week (archived + flagged
        'needs-transcription' — a human reads them into docs/polls.json).
    Backfilled snapshots are snapshot_type='final' and NEVER feed the prior
    anchor (outcome-leakage rule, 2026-09-20): they exist for concordance
    scoring and the P11 post-season review."""
    session = sb.make_session()
    ngnews = fetch_ngnews247(session, week=None)          # all weeks in feed
    articles = discover_result_articles(session)
    LOG.info("backfill: ngnews weeks=%s, result articles for weeks %s",
             sorted(ngnews.get("weeks", {})), sorted(articles))
    for week in range(1, up_to_week):
        existing = load_snapshot(week)
        if existing and existing.get("snapshot_type") == "final" \
                and any(s.get("state") == "needs-transcription"
                        for s in existing.get("sources", [])):
            LOG.info("backfill wk%d: already archived, skipping", week)
            continue
        raw_dir = ROOT / "data" / "raw" / f"week_{week:02d}"
        sources: list[dict[str, Any]] = [
            {"source": "bbnaijadaily", "type": "full-share", "state": "skipped",
             "entries": [], "quarantined": [],
             "note": "final chart is an image; archived separately below"}]
        if week in articles:
            sources.append({"source": "bbnaijadaily-result-image", "type": "image",
                            **archive_result_image(session, articles[week], raw_dir)})
        parsed_w = ngnews.get("weeks", {}).get(week)
        if parsed_w:
            sources.append({"source": "ngnews247", "type": "rank-only", **parsed_w})
        else:
            sources.append({"source": "ngnews247", "type": "rank-only",
                            "state": "not-in-feed", "entries": [], "quarantined": []})
        sources.append(fetch_manual(week))
        for s in sources:
            if s.get("quarantined"):
                LOG.warning("backfill wk%d polls[%s]: quarantined %s",
                            week, s.get("source"), s["quarantined"])
        # rank-only/image sources only -> anchor must stay un-applied
        anchor = {"applied": False, "method": "none-backfill",
                  "kappa": KAPPA, "clip": round(ANCHOR_CLIP, 6), "shares": {},
                  "shifts": {}, "sources_used": [],
                  "sources_skipped": [s.get("source") for s in sources],
                  "note": "backfilled final data never feeds the prior anchor "
                          "(outcome-leakage rule); concordance + P11 review only"}
        snapshot = {"week": week, "snapshot_type": "final",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "sources": sources, "anchor": anchor}
        save_snapshot(snapshot)
        needs = [s.get("source") for s in sources
                 if s.get("state") == "needs-transcription"]
        if needs:
            LOG.info("backfill wk%d: image archived — human transcription needed (%s)",
                     week, needs)


def save_snapshot(snapshot: dict[str, Any]) -> tuple[Path, None]:
    """Write data/raw/week_XX/polls_snapshot.json (model input, archived) and
    append a human-readable row to docs/polls.json (the hand-log file)."""
    week = snapshot["week"]
    snap_path = ROOT / "data" / "raw" / f"week_{week:02d}" / "polls_snapshot.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False),
                         encoding="utf-8")

    anchor = snapshot["anchor"]
    log_row = {
        "week": week,
        "week_start": None,           # filled by hand if this row matters long-term
        "recorded_at": snapshot["captured_at"],
        "auto_scraped": True,
        "sources": [{"source": s["source"], "state": s["state"], "type": s["type"]}
                    for s in snapshot["sources"]],
        "anchor_applied": anchor["applied"],
        "anchor_shares": anchor["shares"],
    }
    if POLLS_LOG.exists():
        with open(POLLS_LOG, encoding="utf-8") as fh:
            log = json.load(fh)
    else:
        log = {"weeks": []}
    # Upsert semantics: one auto-scrape row per week (re-runs replace their own
    # row instead of duplicating it; human-transcribed rows are separate rows
    # and are never touched by an auto row).
    auto_rows = [w for w in log.setdefault("weeks", [])
                 if w.get("week") == week and w.get("auto_scraped")]
    if auto_rows:
        auto_rows[-1].clear()
        auto_rows[-1].update(log_row)
    else:
        log["weeks"].append(log_row)
    POLLS_LOG.write_text(json.dumps(log, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    LOG.info("snapshot written: %s + %s row for wk%d in %s", snap_path,
             "updated" if auto_rows else "appended", week, POLLS_LOG.name)
    return snap_path, None


def load_snapshot(week: int) -> dict[str, Any] | None:
    """Model-side loader: the archived snapshot for `week`, or None."""
    p = ROOT / "data" / "raw" / f"week_{week:02d}" / "polls_snapshot.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="P3.5 multi-source poll scrape + anchor")
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--backfill", action="store_true",
                    help="recover past weeks (rank-only + result images); never anchors")
    ap.add_argument("--reparse", metavar="PATH", default=None,
                    help="rebuild the week snapshot from an archived "
                         "polls_bbnaijadaily.html (offline recovery after a parser fix)")
    ap.add_argument("--no-live", action="store_true",
                    help="skip network sources; manual log only (offline debug)")
    args = ap.parse_args(argv)

    if args.reparse:
        if args.week is None:
            ap.error("--reparse needs --week N")
        snapshot = reparse_snapshot(args.week, Path(args.reparse))
    elif args.backfill:
        if args.week is None:
            ap.error("--backfill needs --week N (backfills 1..N-1)")
        backfill(args.week)
        return 0

    if args.week is None:
        ap.error("--week is required (or use --backfill --week N)")
    snapshot = collect_snapshot(args.week, live=not args.no_live)
    for s in snapshot["sources"]:
        LOG.info("polls[%s]: state=%s entries=%d", s["source"], s["state"], len(s["entries"]))
    anchor = snapshot["anchor"]
    if anchor["applied"]:
        LOG.info("poll anchor APPLIED from %s: %s",
                 anchor["sources_used"],
                 {k: v for k, v in anchor["shifts"].items() if abs(v) > 1e-9})
    else:
        LOG.info("poll anchor NOT applied (%s) — model runs un-anchored",
                 anchor["note"])
    save_snapshot(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
