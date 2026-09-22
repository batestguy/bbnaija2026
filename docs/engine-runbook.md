# Poll-matrix engine runbook — the Saturday ritual (E-campaign)

**Audience:** whoever runs `python run_weekly.py` on Saturdays.
**Status:** LIVE from the 2026-09-22 overhaul (E0–E4 built; E6 cutover = **Sat
2026-09-26**). This file **supersedes `docs/polls-runbook.md`** for engine
operation — that file remains useful only for the Sep-20-era anchor history and
the transcription workflow (its §6 = §5 here).

---

## 1. What happens automatically on Saturday

```
score_previous (catch-up) → blog scrape (archive-only) → polls (THE input) →
matrix (src/poll_matrix) → aggregate (src/aggregate) → schema gate → review
```

- The **poll fetch is now load-bearing**: the Saturday bbnaijadaily snapshot is
  the week's primary observation. It stays best-effort by contract — a fetch
  failure logs `poll fetch failed (...) — running on seeds only` and the run
  proceeds on the seeded matrix (review shows the thin-window warning loudly).
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
| Mon 20:00 | bbnaijadaily voting opens | widget live from here |
| **Sat 21:00** | voting closes | widget dark afterwards: `state=closed`, no row — run on seeds, never fabricated |
| Sun 19:00 | eviction show | results released as an image → transcribe (§5) |

The run window sits **inside the live-voting period** — that is the point.
Running on Sunday yields `state=closed` and a seeds-only run (correct, not a bug).

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

1. Run log: `polls[bbnaijadaily]: state=live` (state `closed` on a Sunday run
   is expected; `partial`/`empty` needs §6).
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
| `state: closed` | ran after Sat 21:00 | expected; seeds-only run. Next week run inside the window |
| `state: partial` | layout drift (names, no %) | inspect archived HTML, fix `parse_totalpoll`, `--reparse` offline |
| `state: empty` / no container | redesign / different poll id | same; grep archive for `totalpoll-poll-\d+` |
| `unreachable` | HTTP failure | transient; run continues on seeds |
| quarantined labels | new nickname | add alias → `--reparse` |
| ngnews `not-in-feed` | video not posted | constraint row missing only — non-fatal |
| `THIN WINDOW` in review | <3 rows (e.g. seeds only) | honest — decide push vs investigate; CIs widen, never fabricated |
| schema gate rejects | malformed payload | last-good restored automatically; fix, rerun |
| matrix CLI for debugging | — | `python -m src.poll_matrix --week N` rebuilds `data/poll_matrix.csv` offline |
| aggregate CLI for debugging | — | `python -m src.aggregate --week N --out data/predictions.json` reruns model stages only |

Parser drift remains the standing risk: the live fixture is synthetic; the
E6 rehearsal (below) is its first real validation. Archived raw HTML makes
every mismatch recoverable offline.

## 7. Still open before/at the Sep 26 run (E5/E6)

1. **E5 transcription backfill:** wk 1–7 result images → `docs/polls.json`
   (wk-8 done). Every legible week deepens the Sep-26 window.
2. **E5 official bottom/top-N recon:** scan news blogs for official ranking
   reports this season. None found so far; the adapter ships anyway and
   zero rows is a valid state. Record the verdict in `docs/season-recon.md`.
3. **E6 rehearsal (Thu–Fri Sep 24–25):** live-DOM fetch validates
   `parse_totalpoll` for real; full dry run; hand-verify standings against the
   widget; `--reparse` drill on the archived HTML.
4. **E6 cutover (Sat Sep 26):** certified first poll-engine publish inside the
   live window. Rollback = restore the Sep-20 MCMC `docs/predictions.json`
   (untouched until then).
5. **Oct 3:** second run; Sunday ≈ Oct 4 finale; weekly concordance
   (`src/score_week.py`) continues as P11 evidence.
