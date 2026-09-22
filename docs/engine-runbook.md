# Poll-matrix engine runbook — the Saturday ritual (E-campaign)

**Audience:** whoever runs `python run_weekly.py` on Saturdays.
**Status:** LIVE — updated 2026-09-23 after the E6.1 live rehearsal
(rehearsal findings + the corrected widget-timing model are folded in below;
**re-read §2 and §4** — the Saturday expectation changed). This file
**supersedes `docs/polls-runbook.md`** for engine operation — that file remains
useful only for the Sep-20-era anchor history and the transcription workflow
(its §6 = §5 here).

---

## 1. What happens automatically on Saturday

```
score_previous (catch-up) → blog scrape (archive-only) → polls (THE input) →
matrix (src/poll_matrix) → aggregate (src/aggregate) → schema gate → review
```

- The **Saturday in-window fetch will log `state=empty` — that is correct, not
  a failure** (verified live 2026-09-23): during voting the widget renders the
  voting form with zero percentages server-side. The load-bearing Saturday
  inputs are the **transcribed seed rows + carry-forward/momentum** from last
  week's finals. Each week's real shares land after Sat 21:00 close (post-close
  fetch or result-image transcription, §5) and feed the NEXT week's window —
  i.e. the engine is a last-final-plus-momentum predictor on Saturdays. A
  `poll fetch failed (...)` line still just means running on seeds only.
- The blog scrape keeps raw archives accruing but **feeds nothing** (CPI
  retired). A blog failure can never block the run.
- The matrix stage rebuilds `data/poll_matrix.csv` idempotently from
  `docs/polls.json` + `data/raw/week_XX/polls_snapshot.json`.
- Aggregate writes `data/predictions.json`; the schema gate (v2, shape-aware)
  validates it; on PASS it mirrors to `docs/predictions.json` and refreshes the
  last-good archive. A rejected run restores last-good and flags staleness.
- Console review = standings table (share = P(win), 89% CI, momentum, carried/
  unmeasured flags), at-risk list, constraint softenings, data-sufficiency
  block, THIN-WINDOW warning when rows ≤ 2.
- Cost: seconds to ~3 min. No sampling, no R-hat — the honesty gate is the
  review's data-sufficiency block, read by a human before push.

## 2. The poll-week timeline (unchanged)

| When | What | Consequence |
|---|---|---|
| Mon 20:00 | bbnaijadaily voting opens | widget live — but renders the **voting form only** (no numbers server-side) |
| Sat ~18:00 | **run window opens** | poll stage logs `state=empty` **by design** — run proceeds on seeds + momentum |
| **Sat 21:00** | voting closes | post-close widget expected to carry results; a fetch any time after close archives them (see probe below) |
| Sun 19:00 | eviction show | final chart released as an **image** → transcribe (§5) → seed row |

The run window sits **inside the live-voting period** on purpose: predictions
are published BEFORE the close, from last week's finals + momentum. Numbers
for the current week only exist after close — that is the widget's real
behavior, verified live 2026-09-23 (results view is client-side only; every
fetchable URL variant returned zero percentage elements).

**One-time probe (recommended once, after close, before the Oct 3 run):**
`python -m src.scrape_polls --week N` between Sunday and Friday archives the
closed widget (expected `state=closed` WITH entries → grade-A row, auto-row
upserted) and settles the only still-unverified parse state. Respects the
single-writer rule: it is a manual fetch, not a scheduled job.

## 3. How the engine weighs things (2-minute mental model)

- `w = grade × min(n, 5000) × 0.6^age_weeks` — grade A widget (n capped at
  5000), grade A transcribed finals, grade B FB rows, grade C ngnews titles
  (as a top-2 constraint, never shares), grade A pseudo-n-200 official-N rows.
- Latest-wins: same source + same week = one matrix row (`n_collapsed`).
- Carry-forward: actives the poll didn't cover inherit last week's share,
  flagged. Never-measured actives get the minimum measured share, flagged.
- Constraints: full cap/floor when the ordering agrees with the polls;
  halfway pull on conflict (every application logged with before/after).
- 1,000 bootstrap replicates (resample rows + voters) → 89% intervals,
  P(#1)/top3/top5, podium slot probabilities. **Share = P(win)** — the whole
  table is hand-checkable against `docs/polls.json`.
- All tunables live in `config/poll_engine.json` and are stamped into
  `predictions.json → engine.params` every run.

## 4. Saturday verification checklist (2 minutes)

1. Run log: `polls[bbnaijadaily]: state=empty` **is the expected Saturday
   in-window state** (voting form renders server-side; §2). `closed` on a
   Sunday-run or post-close probe is expected WITH entries; `partial`, or
   `empty` when a voting form should be there, needs §6.
2. Quarantine warnings: add any new nickname to `config/housemates.json →
   aliases`, then `python -m src.scrape_polls --week N --reparse
   data/raw/week_XX/polls_bbnaijadaily.html`.
3. Review standings vs the widget: leader should match the poll leader; big
   disagreement = investigate before pushing (the engine IS the polls now).
4. `carried` / `UNMEASURED` flags sane (wk-9: actives absent from the nominated
   poll — Abi/Aikou/Araga/Barry are expected there until they're up for a vote).
5. Constraint lines: `official_bottom_top_n` softening only if recon found a
   real source (§7 — currently none, zero rows is correct).
6. Data sufficiency: rows ≥ 1, weeks listed, THIN-WINDOW warning acknowledged
   if shown — the owner decides whether to push or investigate.
7. Gambit strip: empty while the twist stays released (wk 6+). If
   `config/twist.json` gains active periods, auto-finalists appear with no
   numbers — that is correct.

## 5. Manual transcription workflow (past-week images, FB groups)

Unchanged from `docs/polls-runbook.md` §6 — now it MATTERS more: transcribed
finals are the seed rows that make next week's window real.

1. After Sunday's show: `python -m src.scrape_polls --backfill --week N`
   (archives result images under `data/raw/week_XX/polls_result_image.jpg`).
2. Read the image, append a row to `docs/polls.json` with canonical names —
   e.g. `{"week": 8, "recorded_at": "...", "source": "bbnaijadaily week-8
   result image (transcribed by hand)", "poll": [{"name": "Keivo", "pct":
   19.25, "votes": 119589}, ...], "notes": "transcribed by <initials>"}`.
   The wk-8 row is already in as the template. Unclear numbers → leave that
   housemate out; never guess.
3. The matrix picks new rows up automatically on the next run (grade A,
   provenance `transcribed_seed`, recency-discounted). They never anchor the
   current week retroactively.

## 6. Failure modes & recovery

| Symptom | Cause | Action |
|---|---|---|
| `state: closed` | ran after Sat 21:00 | expected — and should carry entries (post-close probe, §2); entries missing = §5 transcription covers it |
| `state: empty` (in-window Sat) | **expected**: widget renders the voting form during live voting (verified 2026-09-23) | no action — run proceeds on seeds + momentum |
| `state: empty` + no form labels in archive | redesign / different poll id | inspect archived HTML, fix `parse_totalpoll`, `--reparse` offline; grep for `totalpoll-poll-\d+` |
| `state: partial` | layout drift (names, no %) | same — inspect, fix, `--reparse` |
| `unreachable` | HTTP failure | transient; run continues on seeds |
| quarantined labels | new nickname | add alias → `--reparse` |
| ngnews `not-in-feed` | video not posted | constraint row missing only — non-fatal |
| `THIN WINDOW` in review | <3 rows (e.g. seeds only) | honest — decide push vs investigate; CIs widen, never fabricated |
| schema gate rejects | malformed payload | last-good restored automatically; fix, rerun |
| matrix CLI for debugging | — | `python -m src.poll_matrix --week N` rebuilds `data/poll_matrix.csv` offline |
| aggregate CLI for debugging | — | `python -m src.aggregate --week N --out data/predictions.json` reruns model stages only |

Parser drift remains the standing risk, but the E6.1 rehearsal (2026-09-23)
validated the live DOM's `empty` state for real. Still synthetically-tested
only: the `closed`-with-entries state (a post-close probe will be its first
live validation) and the result-article image regex (regression-locked against
the real wk-9 slug). Archived raw HTML makes every mismatch recoverable
offline.

## 7. Open items after the 2026-09-23 rehearsal

1. **DONE — E6.1 rehearsal** (2026-09-23): live DOM validated, full stage trio
   green on real data, gate PASS. Two Saturday bugs found and fixed
   (`2b88c2c`): result-slug regex missed `week-N-vote-poll-result-and-eviction`
   (would have silently skipped the wk-9 image backfill), and `save_snapshot`
   duplicated `docs/polls.json` auto rows on re-runs (now upserts).
2. **DONE — E5 backfill** (`664f8fc`): result images archived for wk6/wk7/wk8.
   **Wk1–5 are unrecoverable** (result posts no longer on the site) —
   permanently gap-flagged; cold-start carry-forward handles it.
3. **Owner, before Sat Sep 26: transcribe wk6 + wk7 images**
   (`data/raw/week_0{6,7}/polls_result_image.*` → `docs/polls.json`, §5).
   Takes the Sep-26 window from 1 seed week to 3.
4. **Post-close probe (once, any day after Sat close):** `python -m
   src.scrape_polls --week N` — archives the closed widget with real
   percentages and validates the last unverified parse state (§2).
5. **E5.2 official bottom/top-N recon:** scan news blogs for official ranking
   reports this season. None found so far; the adapter ships anyway and
   zero rows is a valid state. Record the verdict in `docs/season-recon.md`.
6. **E6.2 — Sat Sep 26: certified first publish.** Expect `state=empty` +
   seeds/momentum run + THIN-WINDOW warning. Rollback = restore the Sep-20
   MCMC `docs/predictions.json` (untouched until then).
7. **Oct 3:** second run (closed wk-9 widget + transcriptions in the window);
   Sunday ≈ Oct 4 finale; weekly concordance (`src/score_week.py`) continues
   as P11 evidence.
