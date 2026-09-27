# Session handoff — 2026-09-26 (E6.2 done: live wk9 data captured, 2 engine/dashboard bugs fixed, first certified publish)

> **SUPERSEDED 2026-09-27** → read **`docs/session-handoff-2026-09-27.md`**
> (dashboard overhauled to owner spec — silhouette podium, position-dodged
> chart with photo chips, 6-source registry; ngnews247 acquisition fixed;
> wk9 final tally protected from a widget-reset overwrite; pushed + deploy
> verified live). This file is build history now — and its "next session"
> advice to UPSERT the wk9 tally midweek was itself superseded on 09-27:
> the vote-to-win widget RESET to a fresh zeroed cycle, so a blind upsert
> would have erased the 242,793-vote final tally. Always check votes are
> nonzero before any upsert — see the 09-27 gotchas.

**Read this first.** This file **supersedes `docs/session-handoff-2026-09-23.md`**
(kept as build history; its header points here). Operational doc for Saturdays:
**`docs/engine-runbook.md`** (§2 timing model corrected this session — re-read
the ⚠ block). Spec: `poll-matrix-engine-spec.md`. Phases: `PHASES.md` E-campaign.

Commits this session: **`d0947bd`** (data + parser + ledger fixes), **`937ca8b`**
(dashboard certification + pairwise fix). **Both pushed; deploy triggered.**

## What happened this session (in order)

1. **Owner asked "where are we / show all data"** → built
   `src/build_data_review.py` (manual-only, never in run_weekly) →
   `docs/data-review.html`, self-contained offline page embedding every
   engine-input file. First version showed CPI/MCMC; owner clarified the
   Bayesian/CPI work is retired → rebuilt around polls/rankings only.
2. **Owner delegated capture: "extract from images, do it yourself."** Key
   findings while doing it:
   - The wk6/7/8 `polls_result_image.png` archives were **byte-identical
     (MD5 7957ca…) — all the site LOGO**. Backfill bug, not three charts.
   - Real charts recovered via a real-browser session (image URLs are
     hotlink-protected; direct curl 404s — fetch inside the page context):
     **wk6 bottom-3**: Yusuf 4.23, Barry 4.06, Gerard 3.84 (evicted);
     **wk7 bottom-3**: Bluethopia 5.40, Araga 4.83, Abi 2.63 (evicted).
     Bottom-3-only reveals → **record rows in docs/polls.json, NEVER seed
     rows** (renormalising 3-of-N would fabricate shares).
   - **Discovered the RESULTS-view click**: the TotalPoll widget renders
     exact pct+votes client-side (`totalpoll-question-choices-item-votes-text`)
     after clicking RESULTS. Server-side HTML stays empty — the auto-stage
     still logs `empty`; the click path is the manual supplement.
   - **poll-43005 is the vote-to-WIN poll**: cumulative finalist tally to the
     Oct 4 finale; votes climb past Sat 21:00 (+64 between 20:33 and 21:17
     captures). Runbook §2 timing model corrected in place.
   - **Old result articles embed the CURRENT poll, not their week's finals** —
     never read article-page widget numbers as historical data.
3. **Owner reported "Yusuf was eliminated"** → web research corrected it:
   **wk8 triple eviction Sun Sep 20 — Yusuf, Bells, Chimsom Chuka out
   (Punch); remaining 10 = finalists; no further evictions.** Ledgers fixed:
   config statuses (also the overdue Abi/Araga wk7 rows), manual_notes.csv
   (+3 sourced rows), actives now = the 10 finalists exactly.
4. **wk9 seed row** in docs/polls.json: Sheba 40.76, Ricky 23.22, Temi Nkem
   11.72, Bluethopia 6.00, Barry 5.58, Aikou 5.00, Tram 3.54, Flora 1.97,
   Oyin 1.43, Keivo 0.80 (total 242,793 at 20:17 UTC capture). Raw captures:
   `data/raw/week_09/widget_results_capture.json` (pre-close) +
   `widget_results_postclose.json`. Agent-capture provenance; upsert-safe
   (human row, auto-stage never touches it).
5. **Follow-ups executed same session**: backfill image-selection fixed
   (logo/thumb filters + size sanity + `content_image_urls()` with tests);
   `parse_totalpoll` extended to read the RESULTS-view markup (real-DOM
   fixture `tests/fixtures/totalpoll_results_view.html` + regression test);
   the 3 stale-fixture test failures fixed by dating fixtures relative to
   now. **Suite: 125 passed.**
6. **Full pipeline ran end-to-end (measured)**: matrix <0.1 s, aggregate
   (1,000-replicate bootstrap) 1.7 s, gate+review <1 s, review-page rebuild
   ~1 s → **≈3–5 s total** (vs the MCMC's 72-min runs).
7. **First certified poll-matrix publish**: Sheba 29.1% share / 86.2%
   replicate-win, Ricky 20.6%, Temi Nkem 14.9%, Keivo 9.1% (wk8→wk9 collapse
   23%→0.8% is why Keivo's CI is huge: [0.7, 20.2]); THIN-WINDOW 2 rows
   disclosed in products + dashboard badge.
8. **Push + dashboard certification**: rendered the live dashboard against
   the new products before pushing — found and fixed:
   - **Engine bug: `pairwise_beat` stored each pair only under its
     alphabetical-first key** → half the P(A>B) map unreachable
     (head-to-head rendered "-"). Now emits both directions (0.862/0.138
     for Sheba–Keivo).
   - Products now carry `roster` passthrough (photo/exit_week/exit_type) so
     house-status cards show photos + exit weeks.
   - Dashboard: podium cards show poll share next to slot prob (three
     identical 86% slot probs alone read as a bug); trajectory chart handles
     the single-week cold start (padded domain, CI whisker dots); track panel
     renders only when scored rows exist.

## Current state (committed, pushed, deploying)

| Thing | State |
|---|---|
| Engine | 2 observation rows (wk8 seed + wk9 vote-to-win); cold-start carry-forward done its job (no carries needed — both weeks cover all actives-of-the-time) |
| Products | `data/predictions.json` week 9, engine poll_matrix, precision full; `docs/` mirror synced |
| Dashboard | Certified vs live products; every panel verified in-browser |
| Gambit | Inert (Flora/Aikou released wk6); `auto_finalists` strip appears only if reactivated |
| MCMC | Retired; `data/predictions.json` legacy file was OVERWRITTEN by the new engine publish this session — the last MCMC artifact survives only in git history (`4d881e5^`) |
| Tests | 125 passed in ~4 s |
| Known pre-existing gap | `state: closed` parse path still never observed server-side (see below) |

## Next session (or owner actions) priority order

1. **Verify the live deploys** once Actions goes green: Pages URL + HF Space
   mirror should show Sheba 29.1% podium. (Was pending at session end.)
2. **Midweek re-capture (any day before Oct 3)**: the vote-to-win tally keeps
   accumulating. Re-run the RESULTS-view click capture (same method as step
   4 above — via browser, then upsert the wk9 row latest-wins), re-run
   matrix+aggregate, push. This sharpens P(A>B) before the finale and makes
   week-over-week momentum real on the dashboard.
3. **Sat Oct 3 (E6.3)**: normal run — by then wk9's row is the seed history;
   expect a 3-row window, real trajectory line, momentum pills populated.
   **Sunday Oct 4 = finale** → grade podium vs reality (E6.4) via
   `score_week.py` flow; the engine's champion call gets its first true test.
4. **Post-close probe (one-time, still open from 09-23)**: any
   `python -m src.scrape_polls --week 9` fetch now happens AFTER the vote-to-
   win understanding — the weekly `state: closed` server-side question is
   mostly moot (there IS no weekly close anymore for the top widget), but
   confirm what the server renders post-finale week for the record.
5. **P11 closeout (E6.5)** absorbs: the wk1–5 unrecoverable-weeks note,
   rank-only ngnews247 telemetry review, Gambit podium reconciliation
   (moot unless a twist returns), legacy MCMC dir cleanup decision
   (`.mcmc_probe*/`, `notebooks/` still on disk, gitignored where noted).

## Gotchas worth remembering (new this session)

- **Never `curl` bbnaijadaily image URLs directly** — hotlink protection
  404s. Fetch inside a real page context (browser) or use the Playwright
  session that worked this time.
- **All three chart images in the wild were the logo** — if a future backfill
  archives something that looks identical across weeks, MD5 it immediately.
- **RESULTS-view numbers are the CURRENT poll** wherever the widget is
  embedded — article pages included. Only the post-show result-image
  transcriptions are historical finals.
- **`parse_totalpoll`'s RESULTS branch** returns `state: live` with entries —
  that's intentional so `rows_from_full_share_source` accepts it; a closed
  widget with entries would still hit the CLOSED_MARKERS branch first.
- **The engine's `canonicalize_rows` expects ID columns** (`sheba`,
  `temi_nkem`) from the matrix; hand-built rows must use IDs too, or shares
  silently aggregate to zero. Diagnosed this session via the "Aikou 100%"
  bootstrap artifact (un-canonicalized rows) — the shipped engine is correct.
- Podium slot probs CAN legitimately be identical (top-3-set-with-confidence);
  that's why the cards now show poll shares too.

## Engine behaviors worth remembering (unchanged, all tested)

- Point estimate never uses voter noise; replicates re-apply carry-forward +
  constraints identically, so bands and point can't drift apart.
- Same-week rerun replaces that week's history row; matrix stage idempotent;
  latest-wins dedupe per (source, week).
- <3 actives degrade honestly; Gambit exclusion driven entirely by
  `config/twist.json`.
- `docs/data-review.html` regenerates in ~1 s (`python
  src/build_data_review.py`) — shows engine-input data only, opens offline.
