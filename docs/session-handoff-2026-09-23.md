# Session handoff — 2026-09-23 (E6 rehearsal done, two Saturday bugs fixed, E5 inventoried)

**Read this first.** This file **supersedes `docs/session-handoff-2026-09-22.md`**
(kept as build history; its header points here). Operational doc for Saturdays:
**`docs/engine-runbook.md`** (updated this session — re-read §2/§4, the
Saturday expectation changed). Spec: `poll-matrix-engine-spec.md`. Phases:
`PHASES.md` E-campaign.

## What happened this session (in order)

1. **Live rehearsal vs bbnaijadaily (E6.1, done 2026-09-23)** — real-DOM probe
   of the wk-9 polls page, plus a full stage trio dry run
   (`poll_matrix → aggregate → products_schema`) on real data. All stages
   green; the wk-8 seed row (grade A, 11 housemates, capped n=5000) flows
   through; gate PASS.
2. **Bug #1 (Saturday showstopper) found + fixed:** the result-article
   discoverer regex required `vote-result`, but the real sidebar slugs are
   `week-N-vote-poll-result-and-eviction` — wk-9's result-image backfill would
   have silently no-oped. Fixed + regression test
   (`test_result_slug_with_poll_and_eviction_matches`).
3. **Bug #2 found + fixed:** `save_snapshot` appended an unconditional
   `docs/polls.json` log row — any re-run duplicated the week's auto row.
   Now **upserts one auto row per week; human-transcribed rows are separate
   and never touched** (`test_snapshot_log_row_is_upserted`). The wk-9 auto row
   my 07:51 probe created is now committed content (all states honestly
   `empty`/`unreachable` — nothing fabricated).
4. **MCMC tests removed** (owner instruction: no more MCMC runs, no need to
   test them). `tests/test_model.py` exercised only the retired sampler and
   hung the suite; deletion is a deliberate override of the earlier
   retire-in-place "legacy tests stay green" note. Suite: **123 passed in ~5 s**
   (was 138 + multi-minute hang).
5. **E5 backfill executed:** result images archived for **wk6, wk7, wk8**
   (wk8 already transcribed = the seed). **Wk1–5 result posts no longer exist
   on the site — permanently unrecoverable**; those weeks stay gap-flagged
   (cold-start carry-forward handles it).
6. **Two commits pushed, both deploys green:** `2b88c2c` (rehearsal findings),
   `664f8fc` (E5 backfill). Pages + HF mirror serving current code.

## ⚠ The widget-timing model (corrected this session — affects everything)

Verified live 2026-09-23 (and against every fetchable URL variant):

| Period | Server-rendered widget content | Snapshot state |
|---|---|---|
| Mon 20:00 → Sat 21:00 (live voting) | **voting form** (name labels + radio inputs, zero percentages; results view is client-side only) | `empty` — **by design, not a failure** |
| After Sat 21:00 close | expected: results view with `totalpoll-choice-percentage` (**never yet observed server-side** — the one pre-close wk-8 archive wasn't kept; next post-close fetch settles it) | expected `closed` **with** entries → grade-A row |
| Post-show result articles | final chart is an **image** (verified wk-6/7/8) | archived for human transcription |

**Consequence for the Sep 26 run:** the in-window poll stage will log
`state=empty` and the run proceeds on **seeds + transcriptions + momentum**
(wk8 seed, wk6/wk7 if transcribed by then, any FB rows). THIN-WINDOW warning
with ≤2 rows is the *expected Saturday shape*, not an anomaly. Each week's
final shares land after close (auto-captured by the next fetch or via
transcription) and feed the **next** week's window — the engine is a
last-final-plus-momentum predictor on Saturdays. The runbook §2/§4 now say so.

**One-time option (owner call, respects single-writer + no-fabrication):**
any fetch after Sat 21:00 close (`python -m src.scrape_polls --week 9`) should
archive the closed widget with real percentages, upserting the wk-9 auto row —
free grade-A data for wk10's window, and settles the "post-close widget"
question above. Do it once between Sun and the next Saturday to learn the
cadence.

## Current state (committed, deployed)

| Thing | State |
|---|---|
| Engine (E0–E4) | built, integrated, gated, dashboard-verified both modes |
| E6.1 rehearsal | **DONE 2026-09-23** — 2 bugs found, fixed, test-locked, deployed |
| E5 backfill | wk6/7/8 images archived; **wk1–5 unrecoverable** |
| E5.1 transcription | wk6 + wk7 images **await the owner** (~15 min, template = wk-8 row in `docs/polls.json`; recipe: runbook §5) |
| E5.2 official-N recon | none found so far; adapter ships, zero rows valid — verdict still to be recorded in `docs/season-recon.md` |
| Tests | 123 passed in ~5 s (`tests/test_model.py` deleted with owner approval) |
| `data/predictions.json` | last-good Sep-20 MCMC content (rollback artifact, untouched); `docs/` mirror identical |
| `data/raw/week_09/` | probe HTML + snapshot archived (states empty); auto row in `docs/polls.json` (upsert-safe now) |

## Next session (or next owner action) priority order

1. **Owner: transcribe wk6 + wk7 result images** into `docs/polls.json`
   (runbook §5; canonical names only, never guess unclear numbers). This is
   the single highest-value 15 minutes left this season — it takes the
   Saturday window from 1 seed week to 3.
2. **Optional single post-close probe** (see widget-timing above) — any time
   after Sat 21:00, before the Oct 3 run.
3. **Sat Sep 26 (E6.2): certified first publish** — runbook §1/§4; expect
   `state=empty` + seeds-only/momentum run + THIN-WINDOW warning; the owner
   reads the review and pushes. Rollback = restore last-good `predictions.json`.
4. **Sat Oct 3 (E6.3):** second run — by then the closed wk-9 widget
   (captured post-close) and any transcriptions make the window real.
   **Sunday Oct 4 ≈ finale** → grade the engine's podium vs reality (E6.4
   concordance continues via `score_week.py`).
5. **P11 closeout (E6.5)** absorbs: cap posture, anchor strength,
   Reddit/Telegram adapters, Gambit podium reconciliation, legacy MCMC
   removal, and the "post-close probe cadence" decision.

## Engine behaviors worth remembering (unchanged, all tested)

- Bootstrap resamples rows **and** voters; point estimates never use voter
  noise. Replicates keep all eligible names before carry-forward.
- Model purity: legacy MCMC products seed nothing (cold start was the Sep-26
  starting point by design).
- Same-week rerun replaces that week's history row; matrix stage is
  idempotent; latest-wins dedupe per (source, week).
- <3 actives degrade honestly (podium fills `min(3, n_active)`).
- Gambit exclusion driven entirely by `config/twist.json` (inert —
  Flora/Aikou released wk6); auto-finalists strip appears if it reactivates.
