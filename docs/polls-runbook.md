# Poll stage runbook — scraping & the poll-anchored prior

**Audience:** whoever runs `python run_weekly.py` on Saturdays (or debugs it).
**Status:** live since 2026-09-20 (owner decision). First anchored run: **Saturday
2026-09-26** (the 2026-09-20 run predates the stage; today's widget was already
closed, so nothing was fabricated).

---

## 1. What happens automatically on Saturday

`run_weekly.py` runs the poll stage **between preprocess and model**:

```
scrape → preprocess → polls (src/scrape_polls.py --week N) → model → gates → review
```

- **Best-effort by design:** if the stage crashes, `run_weekly` logs
  `poll stage skipped (...) — model runs un-anchored` and **continues**. A poll
  failure can never reject the certified run.
- Cost: seconds to ~2 min (3 HTTP fetches + one RSS feed). Model timing unchanged.
- The stage writes two things:
  - `data/raw/week_XX/polls_snapshot.json` — the machine-readable snapshot the
    model reads (archived like every other raw snapshot)
  - a row appended to `docs/polls.json` (`"auto_scraped": true`)
- The console review gains one line: `Poll anchor : APPLIED from ... | anchored: k`
  or `Poll anchor : not applied (model un-anchored)`.

## 2. The poll-week timeline (why timing matters)

| When | What | Consequence for the run |
|---|---|---|
| Mon 20:00 | bbnaijadaily voting opens | widget live from here |
| Mon–Sat | ngnews247 posts "WEEK N VOTE POLL RESULT: X & Y" video titles (rank-only) | RSS gives the newest title per week |
| **Sat 21:00** | bbnaijadaily voting **closes** | after this the widget goes dark: "Voting is Closed … collated by Deloitte" |
| Sun 19:00 | live eviction show | final results released (as an **image** on the site) |

**The Saturday run window is inside the live-voting period** — that is the whole
point: the midweek snapshot captures the freshest pre-close state. If you run on
Sunday instead, expect `state: "closed"` and an un-anchored run (correct, not a bug).

## 3. The anchor (what the model actually does)

- Full-share sources: bbnaijadaily widget (state `live`) + manual rows in
  `docs/polls.json` for the week. Each source's shares are renormalized over the
  names it covers; per housemate the **median across sources** is the anchor
  share `s_i` (robust to one widget being stuffed).
- Location shift on the model's housemate level (alpha column), **pre-centering**:
  `m_i = 0.25 · clip( log( s_i · n ), −log 4, +log 4 )`, `n` = number of anchored
  housemates. Uniform poll ⇒ `log(1)=0` ⇒ no shift. Constants (`KAPPA=0.25`,
  `ANCHOR_CLIP=log 4`) live in `src/scrape_polls.py` and are recorded in every
  snapshot + `predictions.json → priors.poll_anchor` (keep the mirror in
  `notebooks/bbnaija_mcmc.py → PRIORS` in sync).
- **All-zero shift ≡ the un-anchored spec.** Missing snapshot, dark widget,
  uniform poll — the model is mathematically unchanged. Nothing is ever invented.
- **Only `snapshot_type: "midweek"` anchors.** Backfilled `final` snapshots
  (past weeks) are outcome-correlated — they must never enter the likelihood.
- Rank-only data (ngnews247 video titles) never becomes shares. It exists for
  concordance scoring only.

## 4. Saturday verification checklist (2 minutes)

1. Run log line `polls[bbnaijadaily]: state=live entries=11` (state `closed` on a
   Sunday run is expected; `partial`/`empty` needs a look — see §5).
2. Quarantine warnings: `polls[...]: quarantined unmatched labels: [...]` — if a
   new nickname shows up, add it to `config/housemates.json → aliases` (then
   `--reparse`, §5) so the label counts next week.
3. Review line says `Poll anchor : APPLIED from bbnaijadaily, manual | anchored: k`.
4. `predictions.json` sanity: `polls.anchor_applied == true`, `priors.poll_anchor`
   present, podium still plausible (the anchor is deliberately weak — big swings
   in P(#1) mean something else is wrong).
5. Gambit housemates never get a shift (they aren't in the save poll); if one
   appears with a shift, stop and investigate.

## 5. Failure modes & recovery

| Symptom | Cause | Action |
|---|---|---|
| `state: closed` | ran after Sat 21:00 (or on Sunday) | expected; run proceeds un-anchored. Next week run inside the window |
| `state: partial` | widget live but layout drifted (names found, no %) or % missing on some rows | inspect `data/raw/week_XX/polls_bbnaijadaily.html` (archived), fix `parse_totalpoll`, then **`python -m src.scrape_polls --week N --reparse data/raw/week_XX/polls_bbnaijadaily.html`** — offline recovery, no re-scrape needed (the widget may already be closed) |
| `state: empty` / no container | site redesign or different poll id | same as `partial`; check the archived HTML for `totalpoll-poll-\d+` |
| `state: unreachable` | HTTP failure | transient; `run_weekly` continues un-anchored; optionally rerun the stage manually before the model — but never bypass the single entrypoint mid-run |
| `quarantined` labels | new nickname / misspelled choice | add alias to `config/housemates.json`, `--reparse` |
| ngnews `unreachable` / `not-in-feed` | channel-id cache stale or video not posted | concordance gap only — **never** blocks anything |
| stage crash | anything | `run_weekly` catches it and continues un-anchored; debug after the run |

**Parser drift is the main standing risk:** the live fixture
(`tests/fixtures/totalpoll_live.html`) is synthetic (TotalPoll-documented
structure; the real live DOM could not be captured on 2026-09-20 because voting
was closed). The archived raw HTML makes every mismatch recoverable offline.

## 6. Manual transcription workflow (FB groups + past-week images)

Past-week "Vote Result" articles publish the final chart **as an image** (a
WhatsApp screenshot — verified for week 7). The backfill archives the image and
flags the week; a **human** reads the numbers. No OCR ever feeds the model.

1. Backfill: `python -m src.scrape_polls --backfill --week 9` (recovers weeks
   1..8: rank-only ngnews leaders + archived result images under
   `data/raw/week_XX/polls_result_image.jpg`).
2. Open each image, read the percentages, append a row to `docs/polls.json`:
   ```json
   {"week": 7, "week_start": "2026-09-06", "recorded_at": "2026-09-21",
    "source": "bbnaijadaily week-7 result image (transcribed by hand)",
    "scope": "all 13 nominated housemates",
    "poll": [{"name": "Keivo", "pct": 19.25, "votes": 119589}, ...],
    "notes": "transcribed from archived image by <initials>"}
   ```
   Use canonical names from `config/housemates.json`. Unclear numbers → leave
   that housemate out; never guess.
3. Transcribed finals are used by `src/score_week.py` concordance and the P11
   post-season review. They **never** retroactively anchor past predictions.

## 7. Where everything lives

| Artifact | Path |
|---|---|
| Scraper + anchor builder | `src/scrape_polls.py` |
| Model anchor consumption | `notebooks/bbnaija_mcmc.py` → `load_poll_anchor`, `poll_shift_vector`, `build_model(poll_shift=…)` |
| Stage wiring (best-effort) | `run_weekly.py` → `cmd_polls` |
| Weekly snapshot (model input) | `data/raw/week_XX/polls_snapshot.json` |
| Raw widget HTML (recovery source) | `data/raw/week_XX/polls_bbnaijadaily.html` |
| Raw result images (transcription source) | `data/raw/week_XX/polls_result_image.jpg` |
| Human-visible log | `docs/predictions.json` → `polls` block; `docs/polls.json` |
| Channel-id cache | `data/raw/ngnews_channel_id.txt` |
| Decision record | `knowledge.md` (2026-09-20 entry), `AGENTS.md` (modeling rules), `docs/session-handoff-2026-09-20.md` |
