"""BBNaija 2026 Predictor — P3 data acquisition (blogs/RSS only, no X/Twitter).

Sources (each parser isolated so one layout change breaks one source, never the run):
  1. Google News RSS        — PRIMARY, date-scoped per week, stable schema.
  2. Wikipedia S11 tables   — structured ground truth: exits, nominations, Gambit shares.
  3. BellaNaija             — month archive listing.
  4. Punch                  — bbnaija tag page.
  5. DStv / Africa Magic    — news listing (JS-heavy; degrades gracefully).
  6. Legit.ng               — tag page, supplementary mention counting.

Design rules (PLAN.md / AGENTS.md):
  - $0 stack: requests + feedparser + BeautifulSoup4 + vaderSentiment. No API keys.
  - Single writer: this module is only ever invoked from run_weekly.py or manually.
  - Unmatched housemate mentions are QUARANTINED (logged + saved), never dropped.
  - Raw snapshots are archived per week so the P4 backfill-bridge can re-read them.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import feedparser
import requests
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

LOG = logging.getLogger("scrape_blogs")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RAW_DIR = ROOT / "data" / "raw"
MANUAL_NOTES = ROOT / "data" / "raw" / "manual_notes.csv"

USER_AGENT = "bbnaija2026-predictor/0.1 (academic project; contact via GitHub issues)"
REQUEST_TIMEOUT = 20
RETRIES = 2
POLITE_PAUSE = 1.0  # seconds between requests to the same host

# --------------------------------------------------------------------------- #
# Config + week calendar
# --------------------------------------------------------------------------- #

def load_housemates() -> list[dict[str, Any]]:
    with open(CONFIG_DIR / "housemates.json", encoding="utf-8") as fh:
        return json.load(fh)["housemates"]


def load_season() -> dict[str, Any]:
    with open(CONFIG_DIR / "season.json", encoding="utf-8") as fh:
        return json.load(fh)


def week_window(season: dict[str, Any], week: int) -> tuple[date, date]:
    """Week N runs [premiere + 7*(N-1), premiere + 7*N); eviction Sunday closes it."""
    premiere = date.fromisoformat(season["premiere_date"])
    start = premiere + timedelta(days=7 * (week - 1))
    end = start + timedelta(days=7)  # exclusive upper bound
    return start, end


def current_week(season: dict[str, Any], today: date | None = None) -> int:
    today = today or date.today()
    premiere = date.fromisoformat(season["premiere_date"])
    return max(1, (today - premiere).days // 7 + 1)


# --------------------------------------------------------------------------- #
# Alias matching + sentiment (central, applied to every source's items)
# --------------------------------------------------------------------------- #

def build_alias_index(housemates: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(alias_lower, canonical_name) pairs, longest aliases first (greedy match)."""
    pairs: list[tuple[str, str]] = []
    for hm in housemates:
        for alias in hm["aliases"]:
            pairs.append((alias.lower(), hm["name"]))
    return sorted(set(pairs), key=lambda p: -len(p[0]))


def match_housemates(text: str, alias_index: list[tuple[str, str]]) -> list[str]:
    """Canonical names whose alias appears in text (case-insensitive)."""
    t = text.lower()
    return [name for alias, name in alias_index if alias in t]


_analyzer = SentimentIntensityAnalyzer()


def vader_compound(text: str) -> float:
    """VADER polarity in [-1, 1]."""
    return float(_analyzer.polarity_scores(text)["compound"])


# --------------------------------------------------------------------------- #
# Polite HTTP
# --------------------------------------------------------------------------- #

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-NG,en;q=0.9"})
    return s


def polite_get(session: requests.Session, url: str, params: dict | None = None) -> requests.Response | None:
    """GET with timeout, one retry on 5xx/network, None on permanent failure."""
    for attempt in range(1 + RETRIES):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            LOG.warning("HTTP %s from %s (attempt %d)", resp.status_code, url, attempt + 1)
        except requests.RequestException as exc:
            LOG.warning("Request failed for %s (attempt %d): %s", url, attempt + 1, exc)
        time.sleep(POLITE_PAUSE * (attempt + 1))
    return None


# --------------------------------------------------------------------------- #
# Item record shape
# --------------------------------------------------------------------------- #

def new_item(source: str, title: str, url: str, published: str | None,
             text: str, week: int) -> dict[str, Any]:
    return {
        "source": source,
        "title": title,
        "url": url,
        "published": published,
        "text_snippet": text[:500],
        "week": week,
        "housemates": [],        # filled by match_housemates
        "headline_feature": False,
        "sentiment": None,       # filled by vader_compound
        "comments": None,        # exposed by source or None (P4 renormalises)
        "shares": None,
        "extra": {},
    }


def annotate(items: list[dict[str, Any]], alias_index: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Fill housemates, headline_feature, sentiment. Returns items without any match
    removed — caller quarantines them."""
    for it in items:
        haystack = f"{it['title']} {it['text_snippet']}"
        it["housemates"] = match_housemates(haystack, alias_index)
        it["headline_feature"] = any(
            alias in it["title"].lower() for alias, _ in alias_index
        )
        if it["text_snippet"] or it["title"]:
            it["sentiment"] = vader_compound(f"{it['title']} {it['text_snippet']}")
    return items


# --------------------------------------------------------------------------- #
# Source 1: Google News RSS (PRIMARY — date-scoped per week)
# --------------------------------------------------------------------------- #

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def fetch_google_news(session: requests.Session, season: dict[str, Any],
                      week: int) -> list[dict[str, Any]]:
    """One query per housemate for the week window; mention per unique URL."""
    start, end = week_window(season, week)
    q_window = f"after:{start.isoformat()} before:{end.isoformat()}"
    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for hm in load_housemates():
        query = f'"{hm["name"]}" BBNaija {q_window}'
        resp = polite_get(session, GOOGLE_NEWS_RSS,
                          params={"q": query, "hl": "en-NG", "gl": "NG", "ceid": "NG:en"})
        if resp is None:
            LOG.warning("google-news: no response for %s (week %d) — skipped", hm["name"], week)
            continue
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:20]:
            url = entry.get("link", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            items.append(new_item("googlenews-rss", entry.get("title", ""), url,
                                  published, entry.get("summary", ""), week))
        time.sleep(POLITE_PAUSE)

    LOG.info("google-news: %d unique items for week %d", len(items), week)
    return items


# --------------------------------------------------------------------------- #
# Source 2: Wikipedia S11 tables (structured exits + nominations + Gambit)
# --------------------------------------------------------------------------- #

WIKI_S11 = "https://en.wikipedia.org/wiki/Big_Brother_Naija_season_11"


def _cells(row) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]


def scrape_wikipedia(session: requests.Session, season: dict[str, Any],
                     week: int) -> list[dict[str, Any]]:
    """Not article mentions: structured facts for the week being scraped.
    Emits one item per week with extra = {exits, nominations, gambit_shares}."""
    resp = polite_get(session, WIKI_S11)
    if resp is None:
        LOG.warning("wikipedia: unreachable — no structured facts this run")
        return []
    soup = BeautifulSoup(resp.content, "lxml")
    facts: dict[str, Any] = {"exits": {}, "nominations": {}, "gambit_votes": {}}

    # Eviction/walk facts live in the voting table rows whose label mentions them.
    for table in soup.find_all("table", class_="wikitable"):
        for row in table.find_all("tr"):
            cells = _cells(row)
            if not cells:
                continue
            head = cells[0]
            joined = " | ".join(cells)
            if "Evicted" in joined or "Walked" in joined:
                facts["exits"][head] = joined
            if "to become The Gambit" in joined:
                facts["gambit_votes"][head] = joined

    # Nominated-per-week summary rows (bottom of the nominations table).
    for row in soup.find_all("tr"):
        cells = _cells(row)
        if cells and cells[0] in ("Nominated", "Evicted", "Walked"):
            facts["nominations"][cells[0].lower()] = cells[1:]

    item = new_item("wikipedia", f"S11 structured facts wk{week}", WIKI_S11,
                    None, json.dumps(facts)[:500], week)
    item["housemates"] = list(facts["exits"].keys())
    item["extra"] = facts
    LOG.info("wikipedia: %d exit rows, nominations summary captured", len(facts["exits"]))
    return [item]


# --------------------------------------------------------------------------- #
# Sources 3–6: blog listing scrapers (title+link level; counts usually absent)
# --------------------------------------------------------------------------- #

def _month_archives_for_week(week: int, season: dict[str, Any]) -> list[str]:
    start, end = week_window(season, week)
    months = {(start.year, start.month), ((end - timedelta(days=1)).year, (end - timedelta(days=1)).month)}
    return [f"https://www.bellanaija.com/{y:04d}/{m:02d}/" for y, m in sorted(months)]


def scrape_bellanaija(session: requests.Session, season: dict[str, Any], week: int) -> list[dict[str, Any]]:
    start, end = week_window(season, week)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for archive_url in _month_archives_for_week(week, season):
        resp = polite_get(session, archive_url)
        if resp is None:
            LOG.warning("bellanaija: archive %s unreachable — skipped", archive_url)
            continue
        soup = BeautifulSoup(resp.content, "lxml")
        for a in soup.select("article h2 a[href], article h3 a[href], h2.entry-title a[href]"):
            url, title = a.get("href", ""), a.get_text(" ", strip=True)
            if not url or not title or url in seen:
                continue
            seen.add(url)
            items.append(new_item("bellanaija", title, url, None, title, week))
        time.sleep(POLITE_PAUSE)
    LOG.info("bellanaija: %d items (week window %s..%s)", len(items), start, end)
    return items


def scrape_punch(session: requests.Session, season: dict[str, Any], week: int) -> list[dict[str, Any]]:
    resp = polite_get(session, "https://punchng.com/tag/bbnaija/")
    items: list[dict[str, Any]] = []
    if resp is None:
        LOG.warning("punch: tag page unreachable — skipped")
        return items
    soup = BeautifulSoup(resp.content, "lxml")
    for a in soup.select("h2 a[href], h3 a[href]"):
        url, title = a.get("href", ""), a.get_text(" ", strip=True)
        if url and title:
            items.append(new_item("punch", title, url, None, title, week))
    LOG.info("punch: %d items (tag page is recency-only; backfill relies on RSS+wikipedia)", len(items))
    return items


def scrape_dstv(session: requests.Session, season: dict[str, Any], week: int) -> list[dict[str, Any]]:
    resp = polite_get(session, "https://www.dstv.com/africamagic/en-ng/news")
    items: list[dict[str, Any]] = []
    if resp is None:
        LOG.warning("dstv: news page unreachable — skipped")
        return items
    soup = BeautifulSoup(resp.content, "lxml")
    for a in soup.select("a[href*='/news/'] h3, a[href*='/news/'] h2, a[href*='/news/']"):
        title = a.get_text(" ", strip=True)
        url = a.get("href", "") if a.name == "a" else (a.find_parent("a").get("href", "") if a.find_parent("a") else "")
        if title and url and len(title) > 15 and not any(url.endswith(i["url"]) for i in items):
            items.append(new_item("dstv", title, requests.compat.urljoin("https://www.dstv.com", url), None, title, week))
    LOG.info("dstv: %d items (JS-heavy page — RSS covers backfill)", len(items))
    return items


def scrape_legitng(session: requests.Session, season: dict[str, Any], week: int) -> list[dict[str, Any]]:
    resp = polite_get(session, "https://www.legit.ng/tag/bbnaija/")
    items: list[dict[str, Any]] = []
    if resp is None:
        LOG.warning("legitng: tag page unreachable — skipped")
        return items
    soup = BeautifulSoup(resp.content, "lxml")
    for a in soup.select("h2 a[href], h3 a[href]"):
        url, title = a.get("href", ""), a.get_text(" ", strip=True)
        if url and title:
            items.append(new_item("legitng", title, url, None, title, week))
    LOG.info("legitng: %d items", len(items))
    return items


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

SOURCES = {
    "googlenews-rss": fetch_google_news,
    "wikipedia": scrape_wikipedia,
    "bellanaija": scrape_bellanaija,
    "punch": scrape_punch,
    "dstv": scrape_dstv,
    "legitng": scrape_legitng,
}


def run_scrape(weeks: list[int], sources: list[str] | None = None,
               out_dir: Path = RAW_DIR) -> dict[str, Any]:
    """Scrape the given weeks; annotate, quarantine, archive per week.
    Returns a summary dict for the console review."""
    season = load_season()
    alias_index = build_alias_index(load_housemates())
    sources = sources or list(SOURCES)
    session = make_session()
    summary: dict[str, Any] = {"weeks": {}}

    for week in weeks:
        matched, quarantined = [], []
        per_source_counts: dict[str, int] = {}
        for source in sources:
            fn = SOURCES[source]
            try:
                raw = fn(session, season, week)
            except Exception:  # noqa: BLE001 — a dead source must never kill the run
                LOG.exception("source %s raised — degrading that source for week %d", source, week)
                raw = []
            raw = annotate(raw, alias_index)
            per_source_counts[source] = len(raw)
            for it in raw:
                (matched if it["housemates"] else quarantined).append(it)

        week_dir = out_dir / f"week_{week:02d}"
        week_dir.mkdir(parents=True, exist_ok=True)
        for it in matched:
            (week_dir / f"{it['source']}.jsonl").open("a", encoding="utf-8").write(
                json.dumps(it, ensure_ascii=False) + "\n")
        (week_dir / "quarantine.jsonl").open("a", encoding="utf-8").write(
            "".join(json.dumps({"title": i["title"], "url": i["url"], "source": i["source"]},
                               ensure_ascii=False) + "\n" for i in quarantined))
        (week_dir / "manifest.json").write_text(json.dumps(
            {"fetched_at": datetime.now(timezone.utc).isoformat(), "week": week,
             "sources": per_source_counts, "matched": len(matched),
             "quarantined": len(quarantined)}, indent=2), encoding="utf-8")

        summary["weeks"][week] = {
            "matched": len(matched), "quarantined": len(quarantined),
            "sources": per_source_counts,
        }
        LOG.info("week %d: %d matched, %d quarantined %s",
                 week, len(matched), len(quarantined), per_source_counts)

    if summary and quarantined:
        LOG.info("quarantine sample (last week): %s",
                 [i["title"][:60] for i in quarantined[:5]])
    return summary


def load_manual_notes(path: Path = MANUAL_NOTES) -> list[dict[str, str]]:
    """P3.6: the DQ/walkout + correction override channel (consumed by P4)."""
    if not path.exists():
        LOG.warning("manual notes file missing: %s", path)
        return []
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    LOG.info("manual notes: %d override rows loaded", len(rows))
    return rows


# --------------------------------------------------------------------------- #
# CLI — smoke:  conda activate bap3 && python -m src.scrape_blogs --week 7
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Scrape BBNaija S11 blog/RSS engagement")
    ap.add_argument("--week", type=int, action="append", required=True,
                    help="season week to scrape (repeatable, e.g. --week 1 --week 2 ...)")
    ap.add_argument("--sources", nargs="*", default=None,
                    help=f"subset of {sorted(SOURCES)}")
    args = ap.parse_args(argv)

    summary = run_scrape(args.week, args.sources)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
