# Session handoff — 2026-09-22 (E0–E4: poll-matrix engine built & integrated)

**Read this first.** This file supersedes `docs/session-handoff-2026-09-20.md`
for session-to-session context. The owner-approved overhaul spec is
`poll-matrix-engine-spec.md` (21 decisions in its §12); phase detail lives in
`PHASES.md` (E-campaign). **Operational doc for Saturdays:
`docs/engine-runbook.md` — read it before the Sep 26 run.**

## Where the project stands

P0–P8 (MCMC) is history — **retired in place** (code stays, run path doesn't).
The poll-matrix engine is built, tested (138 passed = 93 legacy + 45 new, zero
regressions), integrated into the runner, schema-gated, and dashboard-verified
in BOTH engine modes. **No git commit made this session** (owner commits/pushes
per the Saturday ritual — note this is now a large uncommitted changeset).

| Surface | Status |
|---|---|
| `config/poll_engine.json` | NEW — single tunables file (cap 5000, λ 0.6, ε 0.01, window 3, B 1000, seed 20260922, 89%, grades, pseudo-n); stamped into `predictions.json → engine.params` every run |
| `src/poll_matrix.py` | NEW — long-format matrix builder: snapshot+manual rows → Readme §2 schema + `snapshot_id`/`n_collapsed`/`provenance`/`carried`; latest-wins dedupe; Gambit gate (twist.json-driven, currently inert); transcribed-seed rows; `data/poll_matrix.csv` cache; CLI `python -m src.poll_matrix --week N` |
| `src/aggregate.py` | NEW — the engine: filter → weights → full-share aggregation → carry-forward/unmeasured-floor → soften-on-conflict constraints → renormalise → 1,000 bootstrap replicates (rows + voters) → share=P(win), 89% CIs, rank chips, podium, pairwise, momentum=ΔWoW; model-purity gate (legacy products seed nothing); CLI `python -m src.aggregate --week N --out ...` |
| `run_weekly.py` | E3 rewired: score_previous → blog scrape (archive-only, best-effort) → polls (LOAD-BEARING, best-effort) → matrix → aggregate → v2 schema gate → docs mirror → review. MCMC/preprocess stages gone from the path; `--lite`/`--prior-placeholder` removed; `--skip-mcmc` → `--review-only` |
| `src/products_schema.py` | Shape-aware v2 gate: `engine.name=="poll_matrix"` → share/CI/chips rules + share-sum + engine.params + rows_in_window; legacy payloads keep original rules (last published MCMC file stays deployable). 8 new tests |
| `docs/index.html` + `docs/assets/script.js` | Shell kept, data remapped with `engine` branching: trend panel hidden (poll engine), risk panel = lowest-share + bottom-N flags, chips gain momentum + carried pills, pairwise reads the new `pairwise` map, auto-finalists strip (hidden when no active Gambit), poll-engine methodology footer + "How this works" 4-liner. **Headless-Chrome verified both modes: poll-engine payload → trend hidden/footnote swapped/no NaN; legacy payload → byte-equivalent legacy behavior** |
| `docs/engine-runbook.md` | NEW — the Saturday ritual doc (supersedes polls-runbook.md operationally) |
| `PHASES.md`, `AGENTS.md`, `knowledge.md` | E-campaign + authority chain recorded |
| `data/predictions.json` | restored to last-good MCMC content (my E2 smoke output was test-only); `docs/predictions.json` untouched — both still the certified rollback artifact |
| `data/poll_matrix.csv` | live, rebuilt from the real wk-8 seed row (grade A, 11 housemates, capped n=5000) |

## Real-data smoke (week 9, seeds-only — honest state)

With only the wk-8 seed in the window, standings come out **poll-shaped**:
Keivo 0.163 → Temi Nkem 0.144 → Ricky 0.115 → … Chimsom Chuka 0.045 — the
fan-reality alignment the overhaul was built for (vs the MCMC's inverted
podium). 4 actives (Abi/Aikou/Araga/Barry) unmeasured-floored; 4 carried.
THIN-WINDOW warning fires as designed. This is the expected Sep-26 starting
point — E5 transcription + the Saturday snapshot deepen the window.

## Engine behaviors worth remembering (all tested)

- **Bootstrap has two layers** (rows + voters): without voter resampling, a
  one-poll window gives zero-width CIs and P(A>B)=0.5 ties everywhere — the
  wrong direction. Point estimates never use voter noise.
- **Replicates keep all eligible names** before carry-forward — filtering
  zeros would shift replicate shares away from the published point shares.
- **Model purity:** last-good MCMC products seed nothing (no carry-forward,
  no momentum, no history) — the engine chains only from its own
  `engine.name=="poll_matrix"` output. First poll-engine run is a cold start.
- **Same-week rerun** replaces that week's history row (no double-append).
- **<3 actives degrade honestly**: podium slots fill only `min(3, n_active)`.
- **Gambit (spec §6):** active-period members are excluded from standings AND
  matrix, surfaced in `auto_finalists`. Inert now (Flora/Aikou released wk6);
  driven entirely by `config/twist.json` — a late twist activation works
  without code changes.

## What this session did NOT do

- **No commit/push** — owner ritual. Large changeset waiting.
- **No wk 1–7 transcription** (E5.1) and **no official-N recon** (E5.2) —
  both pending; wk-8 seed row is in.
- **No live-DOM validation** of `parse_totalpoll` (synthetic fixture only) —
  E6 rehearsal is its first real test.
- **No re-run of the certified products** — `docs/predictions.json` still the
  Sep-20 MCMC output; the engine first bites in the Sep 26 run.
- Legacy MCMC code/tests/checkpoint dirs untouched (retire-in-place).

## Next session priority order

1. **E5.1 transcription** — wk 1–7 result images → `docs/polls.json` (wk-8
   row is the template). Each legible week deepens the Sep-26 window.
2. **E5.2 official-N recon** — news-blog scan for official bottom/top-N
   reporting this season; wire the adapter if found; record the verdict
   (zero-rows is valid) in `docs/season-recon.md`.
3. **E6.1 rehearsal Thu–Fri Sep 24–25** — live-DOM fetch (validates
   `parse_totalpoll`), full `run_weekly.py --week 9` dry run, hand-verify
   standings vs the widget, `--reparse` drill, then delete/overwrite probe
   snapshots. Verify the runbook §4 checklist by hand.
4. **E6.2 cutover Sat Sep 26** — certified first publish inside the live
   window (before 21:00 close). Rollback = restore last-good
   `predictions.json`. After the run: transcribe nothing mid-week (single
   writer), score Sunday's eviction per runbook §5.
5. **Oct 3 run → Oct 4 finale → P11** absorbs the open decisions: cap
   posture (5000 vs bigger), anchor strength, Reddit/Telegram adapters,
   Gambit podium reconciliation, legacy MCMC removal.
