# Session handoff — 2026-09-27 (dashboard overhauled to owner spec; 6-source registry; ngnews247 acquisition fixed; wk9 final tally protected from reset-overwrite; pushed + live-verified)

> **SUPERSEDED by `docs/session-handoff-2026-10-03.md`** — read that one first.
> Kept as history.

**Read this first.** This file **supersedes `docs/session-handoff-2026-09-26.md`**
(kept as history; its header points here). Operational doc for Saturdays:
**`docs/engine-runbook.md`**. Spec: `poll-matrix-engine-spec.md`. Phases:
`PHASES.md` E-campaign.

Commit this session: **`cf6d182`** (10 files, pushed; Pages deploy verified
green and the live site serves the new build — cache version `?v=20260927j`).

## What happened this session (in order)

1. **Blank-page saga, three causes found and each fixed.** (a) Opening
   `docs/index.html` via `file://` kills the dashboard: `script.js`'s first
   line is a `fetch("predictions.json")` and Chrome blocks fetch on `file://`
   — serve over HTTP always. (b) The detached local server died once and
   produced an "empty dashboard" false alarm; also **port 8765 belongs to the
   owner's other project (APM Bauchi site)** — this repo uses **8899**, started
   via `powershell Start-Process -WindowStyle Hidden` (git-bash mangles `/min`;
   the env's `BACKGROUND` process_type is not implemented). (c) Chrome
   *heuristic-caches* assets served without `Cache-Control` (python
   http.server AND GitHub Pages) — a normal reload can serve stale `script.js`
   forever. Fix: cache-busting `<script src="assets/script.js?v=…">` in
   index.html; **bump `?v=` on every script edit** (comment in the HTML says so).
2. **Dashboard overhauled to owner spec** (each step Playwright-verified,
   console clean at every stage):
   - Photos resolve everywhere now: the standings rows carry no `photo`;
     the `roster` passthrough is merged into `byName` at load. (Sheba's
     "broken" hero photo was this code bug — the file was always valid.)
   - Bayesian vocabulary purged from rendered strings: tooltip "89% CrI" →
     "89% interval"; R-hat badge suppressed for the poll engine; MCMC footer
     branch rewritten as a legacy stub. Registry of engine inputs shown in a
     **Data sources strip** under the chart (all 6 configured sources,
     lit = fed this run, dimmed = no rows in window).
   - Chart: five simultaneous shaded bands removed (overlap mud) →
     end-of-line whiskers + hover-only band; then per owner, **position-dodge
     on the week axis**: per-series lanes (SLOT 34px) in the final-week gutter,
     the axis *widens* by the gutter (linear scale untouched, nothing capped or
     truncated), thin leader lines tie dodged markers back to true endpoints,
     hover hit-tests the dodged x. Photo chips (28px) ride above each whisker
     inside its lane; initials fallback if an image fails.
   - Axis: explicit "wk N" labels; owner revision — **wk 9 + wk 10 runway
     only** (window weeks with no plotted rows stay off the axis; `P.week+1`
     drives the runway tick automatically).
   - House status: full 24-person roster; exits **dimmed, not blurred**
     (owner), status label carries the message ("evicted wk 7" etc.).
   - Layout compacted: chart + sources in the left column, **rank
     probabilities and at-risk vertically adjacent** in the right (the sources
     panel had silently broken the 2-col grid — fixed).
   - Hero iterations: a top-3 strip was built, then reverted per owner to the
     **winner-only hero (64px, as the original)**; runner-up photos moved to
     the podium cards (48px on w2/w3 — `avatarHTML` added to the slot
     template; podium cards had never had avatars before).
   - **Podium silhouette**: 2nd | 1st | 3rd via CSS `order`, staggered risers
     (min-height 250/195/150px) with metallic `::after` caps (gold/silver/
     bronze), winner centered and raised; under 480px it stacks back to
     natural 1-2-3 order with equal heights.
   - Identical 86/86/86 podium numbers explained and relabeled: winner card
     shows "to win" (its slot prob), runner-up cards show **P(top-3)** — the
     claim that slot makes. Poll share stays as the hand-checkable number.
3. **"Did we use all data / normalize / combine?" — proven, not asserted.**
   Independently reproduced ALL 10 published shares from raw `polls.json`
   pcts: per-row renorm over covered actives, weights grade×min(votes,
   5000-cap)×0.6^age → **wk8 3000 (37.5%) + wk9 5000 (62.5%)**, final renorm —
   exact match to 5 dp. (First attempt showed 3 "mismatches": my own script
   typo'd Tram 3.54 vs the logged 3.53 — engine was right.) Documented
   exclusions: rank-only titles, partial bottom-3 charts, retired CPI/news
   engagement (polls ARE the likelihood).
4. **New sources — searched, verified, wired:**
   - **ngnews247 fixed, first successful parse in project history.** Two
     stacked bugs: hardcoded handle `ngnews24769` is stale (channel is at
     `@ngnews247`), and YouTube's consent wall 302s plain requests so handle→
     channel-id resolution ALWAYS failed (no cache file ever existed — the
     tell). Fix: per-channel config + **SOCS=CAI cookie bypass**.
   - **bbn_scoop (@BBNSCOOP) wired** as a second rank-only source (grade C,
     pseudo-n 50): generic machinery (`YT_POLL_CHANNELS`, `fetch_yt_channel_polls`,
     `fetch_all_rank_channels`, per-channel id caches, `rows_from_rank_channel`
     in poll_matrix with `rows_from_ngnews` back-compat wrapper; collect,
     reparse and backfill paths all channel-aware). Its current titles are
     commentary-style → honest `state: empty` until a canonical
     "WEEK N VOTE POLL RESULT: X & Y" video appears.
   - `Temi` alias added to config/housemates.json — "TEMI & RICKY" titles were
     quarantining Temi Nkem.
   - Live probes: ngnews247 **wk8 leaders = Keivo, Ricky — exactly the
     A-grade widget top-2** (parser validated); wk9 leaders = Temi Nkem, Ricky
     (video 2026-09-22). **Those wk9 leaders were archived as concordance
     telemetry ONLY and NOT injected into the closed wk9 snapshot**: a
     C-grade rank signal contradicting the final A-grade tally must not
     rewrite published standings.
5. **Midweek re-capture attempt → the vote-to-win widget has RESET** (fresh
   cycle, all finalists 0.00%, "Voting has not started"). **NO upsert was
   performed** — latest-wins would have overwritten the 242,793-vote wk9
   final tally with zeros. Reset archived: `data/raw/week_10/totalpoll_reset_capture.json`
   + two record-only telemetry rows in `docs/polls.json` (`poll: []` can never
   seed). The Sep-26 capture stands as the final read of that cycle.
6. **Engine re-run** (`python -m src.aggregate --week 9`): reproduced the
   certified numbers **exactly** (deterministic seed 20260922; diff vs HEAD
   showed zero drift in shares/CIs/probabilities); registry gained `bbn_scoop`;
   docs mirror + `data-review.html` regenerated. `125 tests passed`.
7. **Final audit (28 checks)** before push: products identity data/↔docs,
   coherence (shares sum 1, P(#1) sums 1, pairwise both directions), seed-row
   integrity, 24 photos on disk, no Bayesian leftovers in rendered strings,
   handoff claims vs products. Three "failures" investigated to ground truth:
   two were my script's float-rounding comparisons (browser = truth: 86/100/100
   with honest labels), one was a real discovery — **podium "slot prob"
   (0.862) ≠ chip "P(top-3)" (1.0): different, both-correct quantities** (the
   2nd-place slot is settled; Ricky is certain top-3). Don't equate them in
   future audits.
8. **Committed `cf6d182` + pushed.** Deliberately excluded: `data/` (gitignored,
   local-first policy — the site consumes the `docs/` mirrors) and the stray
   `Screenshot 2026-09-18 013951.png` (pre-existing, not ours). `output/`
   (Playwright artifacts) added to `.gitignore`. Deploy verified green via
   Actions API + live-content markers; live site opened for the owner.

## Current state

| Thing | State |
|---|---|
| Engine | poll_matrix, 2-row window (wk8 seed + wk9 final tally); 6-source registry incl. bbn_scoop; deterministic seed proven again |
| Products | `data/predictions.json` wk9, precision full, `docs/` mirror synced; data-review.html regenerated |
| Dashboard | Live at batestguy.github.io/bbnaija2026 (deploy success); silhouette podium, dodged chart with photo chips, registry strip, winner-only hero |
| ngnews247 | **Works for the first time** (@ngnews247 + SOCS bypass; ids cached in `data/raw/yt_ngnews247_channel_id.txt`) |
| bbn_scoop | Wired end-to-end; honest-empty until a canonical-format poll title appears |
| wk9 data | Final tally preserved intact; fresh cycle at zero until Monday's nomination show opens voting |
| Tests | 125 passed in ~4 s |

## Next session (or owner actions) priority order

1. **Sat Oct 3 (E6.3)**: normal run. The fresh vote cycle becomes the wk10
   observation — capture it once voting opens (nonzero votes = valid cycle;
   zeroed = still new cycle, telemetry only). Both YT channels now flow
   natively; confirm bbn_scoop's first live parse if a canonical video lands.
2. **Sun Oct 4 = finale (E6.4)**: grade the podium via the `score_week.py`
   flow — the engine's first true champion test (Sheba 86.2% to win).
3. Watch BBN SCOOP for canonical-format titles; when one lands, add a fixture
   + regression test mirroring `tests/fixtures/ngnews_rss.xml`.
4. Post-close probe (open since 09-23) stays mostly moot but still unprobed.
5. P11 closeout (E6.5): unchanged from the 09-26 handoff (unrecoverable
   weeks note, ngnews telemetry review, legacy MCMC dir cleanup decision).

## Gotchas worth remembering (new this session)

- **Port 8765 = the APM Bauchi project's server.** Use 8899 for this repo.
  Start detached with `powershell Start-Process -WindowStyle Hidden`; the
  hidden server can die — check `curl localhost:8899/predictions.json` before
  blaming the page.
- **Chrome heuristic-caches localhost and Pages assets** (no Cache-Control):
  bump `script.js?v=` on EVERY script edit. A "stale page" report is cache or
  dead-server first, code second.
- **The vote-to-win widget RESETS between cycles.** Before ANY upsert, check
  votes are nonzero; a zeroed capture is a new cycle — archive as telemetry,
  never seed (latest-wins would erase the previous cycle's final tally).
- **YouTube rank channels need the SOCS=CAI cookie** for handle resolution
  (consent wall). IDs are cached in `data/raw/yt_<source>_channel_id.txt`;
  delete a cache file to force re-resolution after a handle move.
- **Rank-channel leaders for a CLOSED week are concordance-only** — never
  inject into a closed snapshot even as a constraint row.
- **BBN SCOOP titles are not canonical yet**; the parser returns honest
  empty. Canonical format: "… WEEK N VOTE POLL RESULT: NAME & NAME …".
- **Slot prob ≠ P(top-3).** Podium cards and rank chips show different,
  both-correct engine quantities (0.862 vs 1.0 for Ricky is correct).
- **`data/` is gitignored by policy** — audits read `docs/` mirrors; only
  `docs/` ships to the site.
