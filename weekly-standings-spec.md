# weekly-standings-spec.md
## BBNaija 2026 Predictor — Weekly Final-Standings Predictions & Final Workflow

> **Status:** Draft spec from requirements interview (2026-09-09). Awaiting user approval.
> **Supersedes (pending fold-in):** the "objective priors" rule in `PLAN.md` §4, the modeling rules in `AGENTS.md`, and the priors line in `knowledge.md`.
> **No production code written.** Per repo gate: `PLAN.md` approval still precedes any implementation; this spec defines the *deltas* to fold into `PLAN.md` after approval.

---

## 1. The request, precisely

> "Do I get posterior predictions weekly? Lets draft the final workflow" — clarified from the typo "weakly". The intent is **weekly prediction cadence**: the model is re-run and its posterior predictions are re-published every week of the season, and each publication reads as **predicted final standings for the final Sunday** (winner, runner-up, 2nd runner-up), continuously improved as each week's new data accrues.

Season grounding (verified Sep 2026): BBNaija seasons run ~10 weeks (S10: 71–90 days depending on source; housemates evicted weekly on Sundays; winner announced on the final Sunday). So the product is **~9–10 weekly prediction snapshots**, one per Saturday run, each answering: *"As of this week, who wins on the final Sunday — and who takes 2nd and 3rd?"*

User's own framing (interview, round 1 & 3, verbatim intent): *"A winner will be announced on final Sunday, I think model ran should tell us final standings for every Sunday aka predictions; the scraping will be done per week; some housemates may not be up for eviction every week"* and *"Previous weeks train the model but use new data to improve it, it's continuous till the end."*

---

## 2. Interview decisions (traceable ledger)

| # | Question | Decision |
|---|---|---|
| D1 | What "weekly" means | Every-Sunday final standings published from weekly Saturday runs; scraping per week; AtRisk varies weekly (not every housemate nominated every week) — *(free text)* |
| D2 | Extra trend metrics? | **Chart is enough.** No momentum leaderboard, no WoW-delta strip, no rise/fall arrows. The trajectory chart (top-5 medians + 89% CrI bands) already communicates trends |
| D3 | Cadence | **Saturday-only**, as planned (~2 h manual window, one run per week for ~10 weeks) |
| D4 | Standings computation | **Both panels**: headline = finale-win probabilities; secondary = this-Sunday at-risk ranking. Plus a **proper ranking**: likely winner → runner-up → 2nd runner-up — *(free text)* |
| D5 | Priors | **Adopt weakly-informative priors**, replacing the objective-prior rule |
| D6 | Ranking display | "Lets do some ranking" — rank-probability machinery (depth resolved by D12) |
| D7 | Evicted housemates | **Evicted badge + place**: stay visible, "evicted wk N — final place X"; table reads like true final standings once the season ends |
| D8 | Cold start | Publish **continuously from week 1 till the end** — prior weeks train, new weeks improve; no suppression weeks — *(free text)* |
| D9 | Gambit & podium | **Runner-up eligible**: a Gambit housemate may be projected runner-up / 2nd runner-up (they hold a finale slot), but P(#1) ≡ 0 |
| D10 | At-risk panel | **Relative risk rank** — keep Cox PH; rank nominated housemates by posterior relative hazard; no absolute eviction percentages |
| D11 | Mid-week DQ / walkout | **Treat as eviction** via `data/raw/manual_notes.csv`; row frozen with "disqualified wk N" badge |
| D12 | Rank depth | **Full machinery**: P(#1), P(top-3), P(top-5) per housemate, powering podium + tie indications |
| D13 | Missed Saturday | **Backfill-bridge**: next run scrapes the missed week from archived blog/RSS data; series stays complete, bridge clearly labeled |
| D14 | Weekly anchoring | **Snapshot + projection side-by-side**: headline = current-posterior standings; secondary readout = trend-projected podium (β_i momentum extrapolated to the finale) |
| D15 | Prior defaults | **Standard weakly-informative set**: Normal(0, 2.5) fixed effects · HalfNormal(1) variance components · LKJ(2), on standardized predictors |

---

## 3. Modeling spec (deltas against `PLAN.md` §4)

### 3.1 What changes

**Priors — REPLACED (D5, D15).** All predictors standardized first (week index `t` centered/scaled; VADER sentiment z-scored; `AtRisk`/`Twist` stay 0/1). Then:

| Parameter family | Old (objective) | New (weakly-informative) |
|---|---|---|
| Fixed effects (α, β, γ, δ, θ, η) | Normal(0, 10) | **Normal(0, 2.5)** |
| Variance components (σ² of α_i, β_i) | HalfCauchy(5) | **HalfNormal(1)** |
| Correlation structure (α_i ↔ β_i) | LKJ(1) | **LKJ(2)** (mild shrinkage toward uncorrelated) |
| Show-history priors | none | none (unchanged) |

Rationale: flat/wide priors on a log-link count model with one season of data produced implausibly confident posterior HDIs; the weakly-informative set regularizes tails without dominating the likelihood. Every prior value is still printed in the run log (auditability rule retained).

**Standardization note (new):** the standardization parameters (means/scales of `t`, `sentiment`) must be stored in the run record so the trend projection (§3.3) and any future re-run transform consistently.

### 3.2 What stays byte-for-byte (frozen)

- **Gambit eligibility filter:** `WinProb_i = 0.0` if `GambitFlag_i == 1`, else `exp(μ_i) / Σ_{j ∉ Gambit} exp(μ_j)` — zeroed in the posterior predictive, never down-weighted. `GambitFlag`/`Twist` still read from `config/twist.json`.
- **Count sub-model:** `log(μ_it) = α + α_i + (β + β_i)t + γSentiment + δAtRisk + θTwist + η(Twist_it·β_i)`.
- **Cox eviction sub-model** with shared `α_i` frailty (D10 keeps it relative-hazard only).
- **BMA:** 3 candidates (momentum-heavy / baseline-heavy / post-Twist heteroscedastic σ²_β spike), Pseudo-BMA+ via ArviZ LOO ELPD with bootstrapping.
- **Sampling:** 4 chains × 2000 draws; convergence gate R-hat < 1.01, reject run → keep last good `predictions.json` + staleness flag. `--lite` fallback still labels `precision`.
- **CPI formula, VADER, blogs/RSS-only sourcing, $0 ceiling, manual-only Saturday, single writer, no cron, no X API, no backtesting** — all unchanged.

### 3.3 New: ranking + podium machinery (D4, D6, D9, D12, D14)

Computed from the existing **10,000 Dirichlet-Multinomial posterior predictive draws** — no new sampling:

1. **Rank probabilities.** For each draw: rank all housemates by that draw's win probability (Gambit housemates are locked at 0, hence never rank #1 but still ordered among the tail). Tally per housemate: `p_rank_1`, `p_top3`, `p_top5`.
2. **Podium projection.** For each slot — winner, runner-up, 2nd runner-up — the projected occupant is the housemate with the highest per-slot probability; the slot probability is published alongside (e.g. "Projected winner: Imisi (34%)"). Gambit housemates are **eligible for runner-up / 2nd runner-up** and **ineligible for winner** by construction (D9).
3. **Statistical-tie indication.** Adjacent table rows whose 89% HDIs overlap render a "statistical tie" marker — rank order is still shown, but over-reading #4 vs #5 is discouraged.
4. **Trend projection (secondary readout, D14).** Headline standings = current-posterior snapshot (steps 1–3). Additionally, per posterior draw, extrapolate each active housemate's linear predictor from week `t_now` to `t_finale` using their `β_i` momentum with uncertainty widening toward the finale (posterior residual variance scaled by horizon), recompute win shares at `t_finale`, and derive a **projected podium**. Published in a separate field; never merged into the headline. As the season progresses the two converge; divergence between them is itself informative.

### 3.4 Standings anchoring (D1, D8, D14)

- Each Saturday run's headline standings answer: *P(housemate is the final-Sunday winner) as of this week's data.* Early weeks = genuinely wide (small n); this is communicated by the HDI width itself, not suppressed (D8).
- Eviction hazard informs standings **only** through the joint model (frailty sharing), and the at-risk panel is displayed separately — the headline number stays "finale win probability", not "survival × win".

---

## 4. Revised weekly workflow (the "final workflow" draft)

Single entrypoint, one Saturday run, ~2 h window:

```
python run_weekly.py [--lite] [--week N]
```

1. **Pull & configure** — `git pull`; load `config/twist.json`, `config/housemates.json`, `config/season.json` (new, see §7).
2. **Scrape this week** — Google News RSS (primary) + BellaNaija/Pulse/DStv parsers (isolated per source, try/except per source, dead source degrades that week's terms only).
3. **Backfill-bridge check (D13)** — if last week has no record, scrape the missing week from archived RSS/blog items; append records flagged `backfilled: true`; listed in `backfilled_weeks`.
4. **Manual overrides** — ingest `data/raw/manual_notes.csv`: mid-week DQ/walkouts → coded as evictions (D11); unmatched housemate aliases → quarantine list printed, never silently dropped.
5. **Preprocess** — VADER sentiment (polarity ∈ [-1,1]), weekly CPI with min-max normalization + logged renormalization, `AtRisk` coded from nomination/show-report posts (varies weekly, D1), `Twist`/`GambitFlag` from config.
6. **MCMC** — cumulative data (all weeks so far, D8), standardized predictors, new weakly-informative priors (§3.1), 4×2000 draws, ZINB joint survival, 3-model BMA.
7. **Posterior products** — 10k draws → win probs (Gambit zero-out) → rank probabilities + podium + statistical ties (§3.3) → trend-projected podium (§3.3.4) → at-risk relative-hazard ranking (D10) → per-housemate `history` append.
8. **Gate** — R-hat < 1.01 else reject: keep last good `predictions.json`, flag stale. `--lite` → `precision: "lite"`.
9. **Console review** — podium, biggest rank changes implied by the draws, at-risk list, convergence summary. Human decides to push.
10. **Push → deploy-only Actions** (push-triggered, no cron) → HF Space (Static) + Dataset repo + GitHub Pages mirror, all from the same commit.

Mid-week: nothing runs. No schedulers, single writer (unchanged).

---

## 5. Schema deltas

### 5.1 `config/season.json` (NEW — needs PLAN.md file-list amendment)

```json
{
  "season": 2026,
  "label": "BBNaija Season 11",
  "premiere_date": "2026-07-26",
  "finale_date": "2026-10-04",
  "eviction_day": "sunday"
}
```

Week numbers derive from the season calendar (premiere → finale), so a missed run leaves a *calendar* gap that backfill-bridge fills — runs never renumber weeks (D13).

### 5.2 `data/predictions.json` (additive changes; `PLAN.md` §5 shape preserved)

```json
{
  "generated_at": "2026-09-05T10:30:00Z",
  "week": 3,
  "week_start": "2026-08-08",
  "precision": "full",
  "twist_scenario": "provisional",
  "rhat_max": 1.004,
  "model_weights": {"momentum": 0.45, "baseline": 0.35, "heteroscedastic": 0.20},
  "priors": {"fixed_effects": "Normal(0, 2.5)", "variance": "HalfNormal(1)", "correlation": "LKJ(2)", "standardized": true},
  "missing_weeks": [],
  "backfilled_weeks": [1],
  "podium": {
    "winner":          {"name": "Imisi", "prob": 0.34},
    "runner_up":       {"name": "Dede",  "prob": 0.21},
    "second_runner_up":{"name": "Faith", "prob": 0.14}
  },
  "trend_projection": {
    "method": "beta_i momentum extrapolation to finale",
    "horizon_week": 10,
    "podium": ["Imisi", "Faith", "Dede"]
  },
  "at_risk": [
    {"name": "Goro", "relative_hazard": 2.31, "nominated": true},
    {"name": "Dede", "relative_hazard": 1.02, "nominated": true}
  ],
  "housemates": [
    {
      "name": "Imisi", "photo": "assets/photos/imisi.jpg",
      "status": "active", "evicted_week": null, "final_place": null,
      "gambit_flag": 0,
      "win_prob_median": 0.18, "hdi_89": [0.11, 0.26],
      "p_rank_1": 0.34, "p_top3": 0.71, "p_top5": 0.92,
      "statistical_tie_with": ["Dede"],
      "history": [{"week": 1, "median": 0.09, "hdi_89": [0.04, 0.15]},
                  {"week": 2, "median": 0.13, "hdi_89": [0.07, 0.20]}]
    },
    {
      "name": "Sultana", "photo": "assets/photos/sultana.jpg",
      "status": "disqualified", "evicted_week": 2, "final_place": null,
      "gambit_flag": 0,
      "win_prob_median": 0.0, "hdi_89": [0.0, 0.0],
      "p_rank_1": 0.0, "p_top3": 0.0, "p_top5": 0.0,
      "statistical_tie_with": [],
      "history": [{"week": 1, "median": 0.05, "hdi_89": [0.01, 0.11]},
                  {"week": 2, "median": 0.0,  "hdi_89": [0.0, 0.0]}]
    }
  ]
}
```

Field notes:
- `status`: `active | evicted | disqualified` (D7, D11). `final_place` stays `null` until the real Sunday results make it ground truth; the dashboard renders *projected* place (from podium/rank order) with a "projected" tag, and actual place once known.
- `p_rank_1 ≡ 0` for `gambit_flag == 1`; they remain eligible in `p_top3`/`p_top5` and podium runner-up slots (D9).
- `at_risk` = **relative** hazards only (D10); `nominated: true` rows only.
- `priors` block records exactly what was used (auditability rule).
- `history` rows are never rewritten after publication except by an explicit backfill-bridge, which logs to `backfilled_weeks`.

### 5.3 `daily_cpi.json` — unchanged except two optional fields

`"backfilled": true` on bridge-filled records; `"dq_source": "manual_notes"` on override-coded evictions.

---

## 6. Dashboard deltas (`docs/index.html` + `docs/assets/script.js`)

**Unchanged (D2):** trajectory line chart — top-5 medians + 89% CrI bands, photo+name end-labels, dropdown to add housemates. No new trend metrics.

**Added:**
1. **Podium strip** — projected winner / runner-up / 2nd runner-up with slot probabilities (from `podium`); Gambit names allowed in 2nd/3rd with the banner cross-referencing their P(#1) = 0 (D9).
2. **Rank-probability chips** — per housemate row: P(#1) · P(top-3) · P(top-5) (D12).
3. **Statistical-tie markers** — adjacent overlapping HDIs (D12), rendered as a subtle "≈" between rows.
4. **At-risk panel** — this Sunday's nominated housemates ranked by relative hazard; explicitly labeled *relative* risk, no percentages (D10).
5. **Status badges** — `evicted wk N` / `disqualified wk N` / final place when known; evicted rows stay visible, grayed (D7, D11).
6. **Trend projection readout** — secondary, clearly separated from the headline snapshot (D14).
7. **Data-quality line** — staleness badge, `missing_weeks`/`backfilled_weeks`, precision label (unchanged rules).

**Retained:** Gambit warning banner, Pre/Post-Twist scenario toggle (labeled "provisional"), methodology note — now also stating the weakly-informative prior choice and that cross-blog engagement is a correlated index.

---

## 7. File deltas summary (for the post-approval fold-in)

| File | Change |
|---|---|
| `PLAN.md` | §4 priors replaced (§3.1 here); §5 schemas replaced (§5 here); §6 dashboard + workflow updated (§4, §6 here); file list gains `config/season.json` |
| `AGENTS.md` | Modeling rules: priors bullet replaced; add rank/podium machinery + weekly standings intent; keep all other rules verbatim |
| `knowledge.md` | Mirror the priors change + weekly-standings product definition |
| `config/season.json` | NEW (small: premiere/finale dates drive week numbering) |
| `data/raw/manual_notes.csv` | Documented as the DQ/walkout + correction override channel (already planned; now load-bearing for D11) |

No other file-list changes. `specification.md` remains the post-approval deliverable that implements all of this.

---

## 8. Validation & success criteria (in-season only — no backtesting)

1. **Convergence gate** — R-hat < 1.01 every week; run rejected otherwise (unchanged).
2. **Prior predictive sanity** — with the new priors, prior predictive win-share draws must look like a plausible 10-week season (no 0%/100% pathologies) — checked once before week 1.
3. **Posterior predictive coverage** — weekly, the fraction of observed weekly engagement counts inside their 89% posterior predictive intervals should be ~89%; systematic undercoverage is the alarm that the priors fix didn't take.
4. **Eviction concordance** — track, week over week, whether the at-risk panel's top-ranked nominated housemate matches the actual Sunday eviction (concordance rate reported in the run log as the season progresses).
5. **Podium stability** — week-over-week podium churn is logged; a podium that reshuffles completely every week is a smell, though churn is *expected* to decrease as data accrues.
6. **Projection convergence** — by the final weeks, snapshot and trend-projected podiums should agree; documented divergence in the final 2 weeks is a modeling flag.

---

## 9. Edge cases (decided)

- **Week-1 cold start:** publish immediately (D8); wide HDIs communicate low information — no suppression logic exists in the code at all.
- **Missed Saturday:** backfill-bridge from archived sources (D13); if archived data is also unavailable for that week, the gap stays and `missing_weeks` flags it — the bridge never fabricates counts.
- **Mid-week DQ/walkout:** treated as eviction that week via `manual_notes.csv` (D11); unconfirmed rumors do NOT enter the data — only logged, sourced notes.
- **Gambit announced mid-season:** `config/twist.json` updated (that's its purpose); `twist_start_week` flips `Twist_it` from that week on; the dashboard banner + "provisional" label switch off only when the twist is officially confirmed.
- **Housemate walks back in / replacement housemates:** add to `config/housemates.json` with entry week; model treats pre-entry weeks as missing, not zero engagement.
- **Statistical ties in podium slots:** if two housemates tie exactly on per-slot probability, canonical-name alphabetical order breaks the tie (documented, deterministic).
- **Finale week:** final Sunday results replace projections with ground truth in the dashboard (model stops; last `predictions.json` archived).

## 10. Open questions (deferred to implementation / later interview)

1. **Projection variance scaling** — exact form of uncertainty widening in the trend projection (default: posterior residual variance × horizon factor); tune on week-1 dry run.
2. **HoH/immunity flags in the at-risk panel** — only if nomination posts reliably expose immunity; otherwise nominated-only (current default, D10).
3. **Season dates** — `config/season.json` needs the real 2026 premiere/finale dates once officially announced; placeholders until then.
4. **How many housemates in the ranked table** — all active housemates vs top-N with the rest collapsed; default all-active (29-housemate S10 precedent suggests a collapsible tail).
