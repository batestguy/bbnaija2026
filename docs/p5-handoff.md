# P5 Session Handoff — Modeling Core (2026-09-13)

**Phase:** P5 `notebooks/bbnaija_mcmc` — code complete, tests green, validation run
**incomplete**. **All P5 code is uncommitted** (see "Working-tree state").

## Where we are in the phase map

| Phase | Status |
|---|---|
| P0 fold-in / git init, P1 recon, P2 scaffold, P3 scrape, P4 preprocess | ✅ committed (HEAD = `15bb99e`) |
| P5 modeling core | ⚠️ code + 38 green tests **on disk only, not committed**; 4×2000 validation run fails at the R-hat gate (NaN), divergences not yet at zero |
| P6 runner → P7 dashboard → P8 deploy | not started |

## What succeeded (do not re-litigate — this is done and verified)

- **Model machinery complete and correct per spec:** ZINB count sub-model with the
  frozen formula `log μ = α + α_i + (β + β_i)t + γSent + δAtRisk + θTwist + η(Twist·β_i)`;
  Cox eviction sub-model sharing `α_i` as frailty; sum-to-zero centered offsets;
  Gambit zero-out in posterior predictive (P(#1) ≡ 0, runner-up/top-3/top-5 eligible);
  10k Dirichlet-Multinomial draws → median + 89% HDI; rank/podium without replacement;
  deterministic alphabetical tie-break; statistical-tie markers; trend-projected
  secondary podium; at-risk panel; weekly-standings products.
- **38/38 tests green** under `bap3` (`PYTENSOR_FLAGS="mode=FAST_COMPILE"`), no network.
- **BMA works end-to-end:** pseudo-BMA+ via ArviZ LOO pointwise (`loo_i` field on
  arviz 0.16), Bayesian-bootstrap weights, per-candidate R-hat gate → weight 0,
  equal-weight fallback, `precision` label stamped at assembly (never silent).
- **Likelihood rewrite (robustness win):** replaced pymc 5.8's masked-observed ZINB RV
  (which trips a pytensor 2.15 optimizer assert under FAST_COMPILE) with an explicit
  masked Potential + pointwise `y_loglik` deterministic — also what the LOO consumes.
  Cox terms rewritten as pure vector ops (dot products + masked logsumexp, no fancy
  indexing) after the same class of optimizer crash.
- **Sum-to-zero offsets cut divergences ~2×** on the validation run (63→28 momentum,
  467→232 baseline) — the common-shift ridge was real; the fix is in and stays.
- **Environment knowledge:** `bap3` verified (pymc 5.8.0 / arviz 0.16.1 / numpy 1.24.4);
  8 logical cores; no BLAS (NumPy C-API fallback) — sampling is ~2–4 s/iter under
  FAST_COMPILE, ~15 min per candidate at 4×2000 with parallel chains.
- **Windows multiprocessing fix:** `sample_model` defaults to sequential chains;
  `BBN_MCMC_CORES` env overrides for script-mode runs (pytest + spawn re-collects the
  suite in children → hang). Script mode with a proper `__main__` guard is safe.

## What failed (with numbers, so nobody repeats these)

### Validation-run attempts (synthetic 12-housemate / 6-week season)
1. **Sequential 4×2000:** baseline ~2.5 min, momentum >50 min (sequential chains
   wasted the box) → killed. Relaunch with `BBN_MCMC_CORES=4`.
2. **Pre-sum-to-zero parallel run:** momentum 63 divergences, baseline **467** —
   identified the `α + α_i` / `β + β_i` unidentified common-shift ridge. Fixed by
   centering (`offsets = raw - raw.mean(axis=0)`).
3. **Post-fix run (the current best evidence):** momentum **28 div**, baseline
   **232 div**, heteroscedastic **36 div** (4×2000 each, ~15/36/35 min). Then the
   run **crashed at the gate**: baseline R-hat = **NaN** → `ModelRejected` →
   no record, ~2.6 h of draws lost (no checkpointing).
4. **NaN R-hat on 4 chains = zero within-chain variance somewhere.** Leading
   hypothesis: a HalfNormal variance component (`s_beta`, mode at 0) funnels to ≈0,
   freezing scaled coordinates. **Unverified** — diagnostic pass not yet run.
   Baseline (HalfNormal(0.5) scale) had the *most* divergences — consistent.

### Dead ends (do not retry)
- **nutpie 0.9.1 on pytensor 2.15:** numba backend cannot codegen fused Composite ops
  (e.g. `Composite[Log, Add]`) inside `CAReduce` reductions — hits our ZINB potential
  and pymc's own logsumexp. A dot-flatten workaround fixed one node but more remain.
  Dead end on this pinned stack.
- **Stan rewrite:** would be faster per-draw but violates the AGENTS.md stack pin and
  means porting ZINB potential + Cox partial likelihood. Rejected (user agreed).
- **pymc masked-observed RVs and fancy-indexed Cox potentials** under
  pytensor 2.15 FAST_COMPILE — both trigger `local_add_canonizer` /
  `IncSubtensor` optimizer asserts. Keep the Potential + vector-op formulations.
- **arviz 0.16 API traps:** `az.loo` on raw ndarrays needs a wrapped dataset with
  posterior + log_likelihood groups; pointwise field is `loo_i` (not `elpd_i`).

### Session-logistics lessons
- Long runs: use `nohup ... > /tmp/x.log 2>&1 &` + poll `sleep N; grep ...` — the run
  survived a client disconnect AND a machine sleep (~2 h) because of nohup.
- `process_type=BACKGROUND` is not implemented in this tooling; timeouts kill output
  buffering — never pipe through `tail` (buffers until EOF); stagger prints.
- MCP/helper processes restarting at 08:45 was the sleep boundary, not a crash —
  check process CreationDate before assuming death.

## Working-tree state (uncommitted)

- `notebooks/bbnaija_mcmc.py` — full modeling core + `--synthetic --full --record`
  CLI + prior-predictive check. **~1070 lines, on disk only.**
- `tests/test_model.py` — 38 tests. **On disk only.**
- `tests/conftest.py` — modified: sets `PYTENSOR_FLAGS=FAST_COMPILE` before pytensor
  imports.
- ⚠️ **If the disk dies, P5 is gone. Committing WIP is action #1 below.**

## Immediate next actions (in order)

1. **Commit P5 WIP** (code + tests + this doc) so the work survives. Message along
   "P5 modeling core WIP: model+tests green, validation blocked on gate".
2. **Diagnose the NaN R-hat / divergences with a small probe** (500×4, FAST_COMPILE
   off, `BBN_MCMC_CORES=4`): log `az.summary` worst R-hat/ESS variable names and
   per-draw divergence vs-parameter scatter. Needed: CLI `--draws/--chains/
   --candidates` args + gate-failure diagnostics naming the worst coords.
3. **Apply the geometry fix the probe indicates.** Likely candidates, cheapest first:
   `BBN_TARGET_ACCEPT` env (0.9→0.95–0.99); lognormal reparam of `s_beta`/`s_spike`
   (HalfNormal → exp(Normal) keeps weakly-informative spirit); non-centered psi.
   Spec rule: priors stay weakly-informative, formulas byte-for-byte.
4. **Re-probe to ~0 divergences + finite R-hat < 1.01**, then full 4×2000 with
   **checkpointing** (save idata per candidate before the next stage; add `--resume`).
5. **Gate criterion decision:** spec says zero divergences. If a small residue
   remains on non-headline candidates only (they get weight 0 anyway), raise with
   the user before bending the criterion — headline (baseline) must be clean.
6. pytest green again → **commit P5 final** → P6 (`run_weekly.py`).

## Commands cheat sheet

```bash
PY=/c/Users/TOSHIBA/miniconda3/envs/bap3/python.exe
PYTENSOR_FLAGS="mode=FAST_COMPILE" $PY -m pytest tests/ -x -q          # fast suite
BBN_MCMC_CORES=4 nohup $PY notebooks/bbnaija_mcmc.py --synthetic --full \
  --record p5_full_validation.json > /tmp/p5_full_run4.log 2>&1 &      # validation
grep -E "sampled:|R-hat gate|BMA|Error" /tmp/p5_full_run4.log | tail   # progress
```
