# Carry-over validation design (next season)

> Written 2026-10-03, finale-eve (week 10). **Status: design only — nothing in this doc has been
> implemented, and nothing in the engine was changed for it.** This exists so the question "does
> the engine carry information forward, and does that carry-over actually help?" is answered with
> evidence next season instead of opinion.

## 1. Why this doc exists

Finale-eve review of the poll-matrix engine found that the model has almost **no
prediction-to-prediction carry-over**. The only mechanism that transports a previous week's number
into this week's output is `apply_carry_forward()` in `src/aggregate.py`:

- an active housemate not covered by any full-share row this week **inherits last week's
  aggregated share** (logged in `carried`);
- a housemate never measured at all is floored at the minimum measured share (logged in
  `unmeasured_floored`).

That is a *coverage patch*, not a state model. Recency is handled inside the matrix instead, by the
weight decay `λ^Δt` (`config/poll_engine.json`, `lambda_decay: 0.6`) over `window_weeks: 3`, and by
the explicit `dedupe_rule: latest_wins_per_source_week`.

Owner decision (2026-10-03): **leave the engine as-is for the S11 finale** — spec §12 decision #14
forbids parameter tuning and backtesting before the finale — and write this validation design for
S12.

### 1.1 Why the S11 evidence cannot answer the question

The three-week matrix window in the finale run was:

| Week | Rows in window | Full-share sources |
|---|---|---|
| 8 | bbnaijadaily vote-to-save widget (11 rows) | yes |
| 9 | bbnaijadaily vote-to-win tally, transcribed results view (10 rows) | yes |
| 10 | manual Facebook-group final poll (9 rows, pseudo-n) + ngnews247 rank-only constraint | yes (manual, grade 0.7) |

Every one of the 9 actives was covered in week 10, so the finale run reported
`carried = []` and `unmeasured_floored = []` — **the carry-over path had exactly zero effect on the
published numbers.** With n = 1 carry-over-free week there is nothing to measure. A validation
needs weeks where coverage is *incomplete*, which only happens mid-season with a small roster of
live sources.

## 2. What is being tested (and what is not)

Two different things get conflated; keep them separate.

1. **Carry-over as a coverage patch** — `apply_carry_forward()`. Testable only on weeks with
   incomplete coverage.

* **Observation-level recency** — the `λ^Δt` weight decay. This is *inside* the matrix and is
  already exercised every week; it is the more likely source of any real temporal skill, and it is
  also the only lever that can be ablated without touching coverage.

**Not tested here:** hierarchical partial pooling / data-sufficiency shrinkage. That is a different
upgrade (it borrows strength *across* housemates via a shared prior rather than transporting one
housemate's own past), and it needs its own design.

## 3. Protocol: leave-one-week-out within-season

Single-season data is short (10 weeks, of which only ~3–4 have full-share coverage), so a
leave-one-week-out (LOWO) protocol is the strongest thing the data supports. It never trains on the
week it scores.

For each evaluable week `W` (a week with at least one full-share row **and** a known exit/outcome
record in `data/raw/manual_notes.csv`):

1. Build the matrix for `W` using only rows from weeks `< W` — i.e. run the normal window but
   exclude `W`'s own rows. This is the *forecast* row.
2. Build the matrix for `W` using rows `≤ W` as normal. This is the *nowcast* row (what the engine
   actually published that Saturday).
3. Score both against `W`'s outcome with the existing machinery in `src/score_week.py`
   (`eviction_probs`, `_safety_scores`, `poll_concordance`) so the metric definitions cannot drift
   between this study and the live track record.
4. Repeat with the carry-over ablation (below) for each of the two variants.

### 4. Ablation arms

Each arm is a config toggle, not a code branch — S12 work is to add the flag, not to fork the
engine.

| Arm | Setting | Question |
|---|---|---|
| A — baseline | `carry_forward.enabled = true` (current) | reference |
| B — no carry | `carry_forward.enabled = false` | does inheriting last week's share beat flooring an uncovered housemate? |
| C — no decay | `lambda_decay = 1.0` | does recency weighting help at all, or is a flat window just as good? |
| D — flat + no carry | B + C | the "memoryless" null |

Arm B is only informative on weeks where `carried != []`; on fully covered weeks B ≡ A by
construction (assert this in the harness — it is a cheap correctness check on the plumbing).

### 5. Metrics

Use the metrics already defined in `src/score_week.py` so results are comparable to
`docs/track_record.json`:

- **Brier score** over the at-risk pool — `mean (p_evict - y)^2`, `y = 1` per exit, double
  evictions counting twice. Poll engine `p_evict(h) = (1/share(h)) / Σ 1/share` over the pool.
- **Eviction concordance** — `poll_concordance().score`: share of housemate pairs where the poll
  save-% ordering agrees with the model's safety ordering. 0.5 = coin flip.
- **Top-hazard hit** — did the model's riskiest pick actually exit? (`top_hazard_hit`, already
  recorded per week.)
- **Winner survival** — did the predicted winner survive the week (`winner_survived`).
- **Forecast vs nowcast gap** — Brier(forecast) − Brier(nowcast) per week. A large positive gap
  means the engine's skill lives in same-week data and the prior weeks add little; this is the
  single most informative number in the study.

Report per-week values, not just means. With this n, a mean alone hides which arm won.

### 6. Decision rule (pre-registered)

Written down *before* seeing results so the outcome cannot be rationalised afterwards:

- **Keep carry-over** (arm A over B) only if A beats B on Brier on **at least 2 of the 3 weeks**
  where `carried != []`, **and** the mean Brier difference is ≥ 0.005 in A's favour.
- **Keep λ-decay** (arm A/C over D) only if the decayed arms beat the flat arms on mean Brier
  across all evaluable weeks by ≥ 0.005.
- **Otherwise:** disable the losing arm via config (never delete the code — the flag stays as the
  documented escape hatch) and record the study outcome in the next session handoff doc.
- If fewer than 3 weeks have `carried != []` in S12, the study is **inconclusive**: publish the
  per-week table, change nothing, and re-run next season. Do not lower the bar to manufacture a
  decision.

### 7. Honest caveats (state these wherever the results are published)

- **n is tiny.** S11 produced ~3 evaluable weeks total, one of which had zero carry-over. Any
  Brier difference here is a hint, not a result.
- **Only one season.** Cross-season backtesting is explicitly out of scope per spec §12 #14; this
  study is within-season LOWO, so it cannot speak to year-over-year drift.
- **Self-selected fan polls.** Full-share sources measure vote-war intensity, not electorate
  share; the ablation compares arms on the *same* noisy inputs, which is the right comparison for
  a *relative* question but says nothing about absolute calibration.
- **The poll-engine risk proxy is not a survival model.** `p_evict ∝ 1/share` is a heuristic;
  differences below the metric's own noise floor are not interpretable. The 0.005 threshold in §6
  is chosen as a round number, not derived — treat it as a floor of interpretability, not a
  significance test.
- **Exit rows are the ground truth and they are human-coded.** DQs and walkouts are entered via
  `data/raw/manual_notes.csv`; a mis-timed row moves a week's outcome. Run
  `python src/score_week.py --validate-notes` before scoring any study week.

## 8. Implementation checklist for S12 (not started)

1. Add `carry_forward` and `lambda_decay` overrides as CLI/env overrides on the matrix stage, or a
   thin study harness that writes temp configs — **do not** add a second writer under `data/`.
2. Write `tests/test_carry_over_study.py` against fixtures only (no network), including the
   "arm B ≡ arm A when `carried == []`" assertion.
3. Emit a study artifact under `output/` (gitignored) — not `docs/`, so study numbers can never be
   confused with published predictions.
4. Run it after the last Saturday of S12 with at least 3 incomplete-coverage weeks available; apply
   §6; record the outcome in `docs/session-handoff-*.md`.

## 9. Pointers

- Engine spec: `poll-matrix-engine-spec.md` (§5.1 dedupe, §12 decision #14).
- Carry-forward code: `apply_carry_forward()` in `src/aggregate.py`.
- Scoring code: `src/score_week.py` (`eviction_probs`, `poll_concordance`, `score_week_row`,
  `update_summary`).
- Live track record: `docs/track_record.json` (S11: `weeks_scored = 1`, `mean_brier = 0.0432`,
  `mean_poll_concordance = 0.5`).
- Tunables: `config/poll_engine.json`.