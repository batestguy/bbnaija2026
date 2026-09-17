# Sprint plan — live by Saturday Sep 19 (compiled 2026-09-16)

> **✅ CLOSED 2026-09-17 — every item delivered two days early.** Real week-8 run certified
> (0 divergences, R-hat 1.0028) and deployed to all three surfaces; P6 runner exit-tested;
> P8 Pages + HF Space + HF dataset live; wk-7/8 data in; dashboard hardened (hero, race
> strip, tracker panel, share cards, mobile pass) and README rewritten with full model
> spec. Session record: `docs/session-handoff-2026-09-17.md`. Remaining work lives there
> (tracker auto-scoring, P9 rehearsal) — this file is kept for the record only.

## The clock (from config/season.json: premiere 2026-07-26, finale 2026-10-04)

- Season week 7 of 10 today (day 52/72). Eviction Sundays: **Sep 20, Sep 27, Oct 4**.
- Remaining Saturday run slots: **Sep 19, Sep 26, Oct 3**. Target: certified real run on Sep 19.
- `config/housemates.json` ledger is stale by 2 exits: **Araga + Abi evicted Day 49 (wk 7, Sun Sep 13)** → 14 active, not 16. Fix via `data/raw/manual_notes.csv` (never edit status by hand).

## Starting state (all committed as of `56dad1c`)

- ✅ P3 scrapers (11 tests), P4 preprocess, P5 model + 38 tests + full products machinery, P7 dashboard + 24 photos, placeholder `predictions.json`.
- ❌ P6 runner, P8 deploy workflow, MCMC geometry fix (NaN R-hat + 28/232/36 divergences), wk-7 data.
- Recovery context: `docs/p5-handoff.md` (probe plan, dead ends, commands).

## Track A — MCMC gate (background/machine-bound)

**PROGRESS 2026-09-16 (evening):** A1+A2+A3 DONE. Root causes found by the
instrumented probes: (1) the "NaN R-hat" that crashed the first validation was
**arviz computing 0/0 on the LKJ correlation diagonal** — a structural constant,
not a pathology (gate now excludes structural NaNs; genuine stuck chains still
reject via huge R-hat); (2) the real geometry bug was the **LKJCholesky
hyper-ridge**: tight candidate scales funnel the Cholesky second row to a
degenerate ray where the correlation is unidentified (baseline 410 div,
R-hat 1.62). Fix: non-centered offsets — sample (z_a, z_b, s_a, s_b, rho)
directly, rho = 2*Beta(2,2)-1 ≡ LKJ(2) at n=2; the BMA candidate knob moved
into s_beta's scale (also fixing the orphaned s_beta bug — candidates had been
accidentally identical priors). Probe result: **baseline 0 divergences,
R-hat 1.0081 PASS** at 500×4 ta=0.95. A4 (full 4×2000 × 3 candidates,
checkpointed) launched 05:17.

| # | Step | Done when |
|---|---|---|
| A1 | Instrument: CLI `--draws/--chains/--candidates`, worst-R-hat-coords diagnostics on gate failure, `BBN_TARGET_ACCEPT` env, per-candidate idata checkpointing + `--resume` | probe runs unattended; a killed run can be resumed |
| A2 | Probe 500×4 (FAST_COMPILE off, `BBN_MCMC_CORES=4`): frozen-coords + divergence-vs-parameter correlation | NaN R-hat root cause named |
| A3 | Fix, cheapest first: `target_accept` 0.95→0.99 → lognormal reparam of `s_beta`/`s_spike` (priors stay weakly-informative; `priors` block updated honestly) | re-probe: finite R-hat, ~0 divergences |
| A4 | Full 4×2000 checkpointed validation (background, ~45–60 min) | R-hat < 1.01 all candidates, 0 divergences headline, record written |
| A5 | **USER DECISION** if residue: spec says zero divergences; non-headline candidates get BMA weight 0 anyway. Accept-with-flags vs iterate | explicit call recorded here |

## Track B — pipe + wire (foreground/edit-bound)

| # | Step | Done when |
|---|---|---|
| B1 | Right-size e2e pytest (15/15 iters) | full suite green < 3 min |
| B2 | P6 `run_weekly.py` (PHASES P6.1–P6.5): orchestrate → gates (schema → R-hat → write) → console review → timing | `--lite` labels precision; doctored run keeps last good file |
| B3 | P8 `.github/workflows/deploy.yml`: push-trigger only, schema-validate step 1, Pages + HF Space/Dataset sync, HF_TOKEN-only secret | test push propagates; bad JSON blocks deploy |
| B4 | Push → public DEMO URL live Thu (placeholder, DEMO-labeled — approved 2026-09-13) | URL reachable from phone |

## Track C — data freshness (~30 min, Wed)

- Scrape wk 6 (refresh) + wk 7. Append manual_notes: Araga eviction, Abi eviction (wk 7, Day 49, Wikipedia/Punch source URLs).
- Verify wk-8 nominations not yet published (eviction Sunday Sep 20) — AtRisk falls back + flags `missing_weeks` if absent.
- Confirm preprocess emits 14 active.

## Timeline

| Day | Track A | Track B/C |
|---|---|---|
| Wed Sep 16 | A1–A2 probe; A3 fix; A4 launched background | B1; B2 P6; C data freshness |
| Thu Sep 17 | A4 verified; A5 decision | B3 P8; B4 public demo URL |
| Fri Sep 18 | — | Rehearsal (P9-lite): full dry run, timing vs 2 h budget |
| Sat Sep 19 | — | `python run_weekly.py` → human console review → push |

## Risks & fallbacks

- **Geometry fix stalls** → Saturday runs `--lite` (honestly labeled `precision: "lite"`), spec-compliant; fix continues next week. Never silent.
- **Real data ≥ 12 weeks should sample easier** than the 6-week synthetic (better-identified `beta_i`); the validation run is the pessimistic case.
- **HF token needed from user** (~15 min) before HF sync works; Pages needs nothing.
- **No new scheduled writers ever** — `run_weekly.py` is the single writer; dev runs of it mid-week are permitted (they ARE the writer).

## Commands

```bash
PY=/c/Users/TOSHIBA/miniconda3/envs/bap3/python.exe
BBN_MCMC_CORES=4 nohup $PY notebooks/bbnaija_mcmc.py --synthetic --full \
  --record p5_full_validation.json > /tmp/p5_full_run4.log 2>&1 &
grep -E "sampled:|R-hat gate|BMA|Error" /tmp/p5_full_run4.log | tail
PYTENSOR_FLAGS="mode=FAST_COMPILE" $PY -m pytest tests/ -q -k "not end_to_end"
cd docs && (nohup python -m http.server 8765 >/tmp/http.log 2>&1 &)
```
