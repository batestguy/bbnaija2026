# BBNaija 2026 Predictor — PLAN.md

> Status: **APPROVED** (2026-09-09). Includes the `weekly-standings-spec.md` deltas: weekly final-standings product, podium ranking machinery, weakly-informative priors, `config/season.json`. Execution order lives in `PHASES.md`.
> Locked constraints: blogs/RSS-only ($0 ceiling, no X API) · local-first MCMC · manual-only Saturday runs (~2 h window) · Gambit math untouched, twist details provisional · HF Spaces Static primary + GitHub Pages mirror · current season only (no backtesting) · weakly-informative priors on standardized predictors.

---

## 1. Twist-status memo (what is verified, what is provisional)

**Verified (Sep 2026, via Channels TV / BellaNaija / Punch / DStv):**

- BBNaija Season 10 ("10/10", 29 housemates, Jul–Oct 2025) is concluded. Winner: **Imisi** (runner-up Dede; Faith disqualified at finale). No "Gambit" twist on record.
- "BBNaija 2026" (would-be Season 11) has no confirmed twist mechanics at time of writing.

**Provisional (kept in the model, untouched):**

- The Gambit eligibility filter is implemented **exactly** as specified:
  `WinProb_i = 0.0` if `GambitFlag_i == 1`, else `exp(μ_i) / Σ_{j ∉ Gambit} exp(μ_j)` — zeroed in the posterior predictive, never down-weighted.
- `GambitFlag_i` and the `Twist_it` indicator are **config, not code**: a `config/twist.json` file (`gambit_housemates: [...]`, `twist_start_week: null`) feeds the notebook and the dashboard toggle. When the real 2026 twist is confirmed, only this file (plus housemate list) changes; model code is frozen.
- Until confirmation, the dashboard labels the toggle "Pre-Twist vs Post-Twist (scenario)" so no viewer is misled.

---

## 2. Blog-only data strategy (why, what, how)

**Why:** X/Twitter removed free read access for new developers (Feb 2026; pay-per-use at $0.005/post read). A season of 6-hourly scraping would cost on the order of ~$140 — violating the $0 premise. Decision: **remove the X API from the architecture entirely.**

**Sources (all free, no keys):**

1. **Google News RSS** (primary) — query per housemate name + `BBNaija`; stable schema, no scraping fragility, no ToS scraping fights.
2. **Entertainment blogs via BeautifulSoup4** (secondary) — BellaNaija, Pulse Nigeria tagging pages, DStv Africa Magic news. One isolated parser per source so a layout change breaks one source, not the run.
3. Manual override file (`data/raw/manual_notes.csv`) for corrections.

**Blog-adapted CPI (the Twitter-native formula cannot survive — there are no QuoteTweets off-Twitter):**

- Per housemate per week: `CPI = 0.4*Comments + 0.3*Shares + 0.2*ArticleMentions + 0.1*HeadlineFeatures`, each term min-max normalised across housemates that week before weighting (preserves the 0.4/0.3/0.2/0.1 shape of the original spec).
- Sources exposing no comments/shares contribute `ArticleMentions`/`HeadlineFeatures` only; weights renormalise over available terms and the renormalisation is logged.
- **VADER sentiment unchanged** (headlines + first paragraphs, polarity ∈ [-1,1]); `AtRisk`/`Twist` remain binary, coded from nomination/show-report posts each week.

**Accepted data limitation (documented, not fixed):** the same voters/commenters can appear across multiple blogs, so per-source engagements are not independent observations and independence cannot be verified. There is no deduplication key available at $0 cost, so nothing is done about this for now: CPI is treated as a correlated engagement index, the limitation is stated in the README and in a methodology note on the dashboard, and no claim of "independent voter sampling" is made anywhere.

---

## 3. Cost accounting (total: $0/month)

| Item | Cost | Basis |
|---|---|---|
| Blog/RSS scraping | $0 | No keys, no quotas |
| MCMC (local, `bap3` or `causality-handbook` on C:, data on D:) | $0 | Sunk hardware; sampling is CPU-bound, no GPU needed |
| GitHub public repo + Actions (push-triggered deploy only) | $0 | Public repos on standard runners are free/unlimited (the "2,000 min" quota applies to private repos) |
| GitHub Pages mirror | $0 | Included |
| Hugging Face Space (Static) + Dataset repo | $0 | Free tier, no card; sleeps when idle — accepted, see §6 |
| **Total** | **$0** | No paid service anywhere in the loop |

---

## 4. Local MCMC workflow (sized to the ~2 h Saturday window)

- **Env:** `bap3` (PyMC 5.8 + ArviZ) or `causality-handbook` (PyMC 5.25 + ArviZ 0.23) — both already on C:. Data and repo working copy on D: (73 GB free; space is not a constraint).
- **Saturday budget:** scrape + preprocess ~10 min · full sampling (4 chains × 2000 draws, ZINB joint survival) ~30–60 min CPU · review + push remainder.
- **Model:** count sub-model `log(μ_it) = α + α_i + (β + β_i)t + γSentiment + δAtRisk + θTwist + η(Twist_it·β_i)`; `α_i` shared as frailty in the Cox eviction sub-model (relative hazards only — no absolute eviction percentages); 3-candidate Pseudo-BMA+ via ArviZ LOO ELPD with bootstrapping; 10k Dirichlet-Multinomial draws → median + 89% HDI; Gambit filter applied in posterior predictive.
- **Weekly standings product (added 2026-09-09):** each Saturday run publishes predicted final standings for the final Sunday — podium projection (winner / runner-up / 2nd runner-up with slot probabilities), per-housemate `p_rank_1` / `p_top3` / `p_top5`, statistical-tie markers on overlapping adjacent HDIs (deterministic alphabetical tie-break), and a secondary β_i trend-projected podium (never merged into the headline snapshot). Gambit housemates: P(#1) ≡ 0 but runner-up/top-3/top-5 eligible. Computed from the existing posterior draws — no new sampling.
- **Prior predictive + coverage checks (added):** prior predictive must draw plausible season shapes (no 0%/100% pathologies); weekly posterior predictive coverage ~89% is the ongoing alarm metric.
- **Priors (weakly-informative, revised 2026-09-09):** predictors standardized first (week index and VADER sentiment scaled; means/scales stored in the run record); fixed effects Normal(0, 2.5), variance components HalfNormal(1), correlations LKJ(2). No informative/show-history priors; every prior printed in the run log and recorded in the `predictions.json` `priors` block so the choice is auditable.
- **Lite fallback:** if a session is cut short, the runner accepts `--lite` (reduced draws); `predictions.json` records the precision label and the dashboard displays it, so precision is never misrepresented.
- **Artifact:** the notebook/script is committed as the run record (seeds fixed). Colab kept only as a documented alternative, not part of the loop — no PAT push-back machinery.

---

## 5. Data schemas

### `data/processed/daily_cpi.json` (appended weekly; one record per housemate-week)

```json
{
  "season": 2026,
  "week": 3,
  "week_start": "2026-07-25",
  "housemate": "Imisi",
  "comments": 120, "shares": 45, "article_mentions": 18, "headline_features": 4,
  "cpi": 0.62,
  "sentiment": 0.31,
  "at_risk": 1,
  "twist": 0,
  "gambit_flag": 0,
  "missing_weeks": [1],
  "sources": ["googlenews-rss", "bellanaija", "pulse"]
}
```

### `data/predictions.json` (rewritten each Saturday)

```json
{
  "generated_at": "2026-09-05T10:30:00Z",
  "week": 3, "week_start": "2026-08-08",
  "precision": "full",
  "twist_scenario": "provisional",
  "model_weights": {"momentum": 0.45, "baseline": 0.35, "heteroscedastic": 0.20},
  "rhat_max": 1.004,
  "priors": {"fixed_effects": "Normal(0, 2.5)", "variance": "HalfNormal(1)", "correlation": "LKJ(2)", "standardized": true},
  "missing_weeks": [], "backfilled_weeks": [1],
  "podium": {
    "winner":           {"name": "Imisi", "prob": 0.34},
    "runner_up":        {"name": "Dede",  "prob": 0.21},
    "second_runner_up": {"name": "Faith", "prob": 0.14}
  },
  "trend_projection": {"method": "beta_i momentum extrapolation to finale", "horizon_week": 10, "podium": ["Imisi", "Faith", "Dede"]},
  "at_risk": [{"name": "Goro", "relative_hazard": 2.31, "nominated": true}],
  "housemates": [
    {"name": "Imisi", "photo": "assets/photos/imisi.jpg",
     "status": "active", "evicted_week": null, "final_place": null, "gambit_flag": 0,
     "win_prob_median": 0.18, "hdi_89": [0.11, 0.26],
     "p_rank_1": 0.34, "p_top3": 0.71, "p_top5": 0.92,
     "statistical_tie_with": ["Dede"],
     "history": [{"week": 1, "median": 0.09, "hdi_89": [0.04, 0.15]}, {"week": 2, "median": 0.13, "hdi_89": [0.07, 0.20]}]}
  ]
}
```

- `precision`: `"full"` or `"lite"`. `twist_scenario`: `"provisional"` until the real twist is confirmed. Convergence gate: `rhat_max < 1.01` or the run is rejected (dashboard keeps last good file and flags staleness).
- `status`: `active | evicted | disqualified` (mid-week DQs/walkouts are treated as evictions via `data/raw/manual_notes.csv`); `final_place` stays `null` until real Sunday results make it ground truth — the dashboard renders *projected* place with a "projected" tag until then.
- `podium` + `p_rank_1`/`p_top3`/`p_top5` come from ranking the 10k posterior predictive draws; `gambit_flag == 1` housemates have `p_rank_1 ≡ 0` but remain eligible for runner-up/top-3/top-5 (they hold a finale slot, just not the prize).
- `at_risk` lists nominated housemates ranked by **relative** Cox hazard — never absolute percentages.
- `trend_projection` is the secondary β_i momentum-extrapolated podium, clearly separated from the headline snapshot; `backfilled_weeks` records backfill-bridge weeks (missed Saturdays rebuilt from archives, never fabricated).
- `history` accumulates per-week median + 89% HDI for every housemate still in the house (evicted housemates keep their rows up to eviction week) — this is what the trajectory chart renders. `photo` points at a committed thumbnail in `docs/assets/photos/`; missing photos fall back to initials avatars, never a broken image.

---

## 6. Deploy flow (manual trigger, cloud mirror)

1. Saturday: `git pull` → `python run_weekly.py [--lite]` (scrape → backfill-bridge if a week was missed → manual-override ingest → preprocess → MCMC → standings/rank products) → review console summary → `git push`.
2. Push fires a **deploy-only** GitHub Actions workflow (no cron, no secrets except an HF token): validates `predictions.json` against schema → syncs JSON to the HF Dataset repo → HF Space (Static) rebuilds → Pages mirror updates from the same commit.
3. **Sleep insurance:** HF Spaces idle-sleep; Pages does not — the two URLs cover each other, and the README pins screenshots + a demo GIF so recruiters see the product even on a cold container.
4. Dashboard (`docs/index.html` + `script.js`, Chart.js):
   - **Main chart — trajectories:** line graph of win-probability median over weeks for the **top 5 candidates**, each with its **89% credible-interval band** shaded around the line. Each line carries the housemate's **photo + name as a text/annotation label at the line end** (photos from `docs/assets/photos/`, initials-avatar fallback). A **dropdown adds any other housemate** to the chart on demand (their band included).
   - **Podium strip:** projected winner / runner-up / 2nd runner-up with slot probabilities (Gambit names allowed in 2nd/3rd, cross-referenced with the banner since P(#1) = 0).
   - **Rank-probability chips:** P(#1) · P(top-3) · P(top-5) per housemate row; **statistical-tie markers** between adjacent rows with overlapping HDIs.
   - **Below-chart metrics panel:** (a) **pairwise difference** — user picks any two candidates, panel shows median difference in win probability with its 89% interval and P(A beats B) from the posterior draws; (b) **likely overall winner** — highest median with HDI, stated with its interval, never as a bare point.
   - **At-risk panel:** this Sunday's nominated housemates ranked by relative eviction hazard, explicitly labeled *relative*.
   - **Status badges:** `evicted wk N` / `disqualified wk N` / final place once known; evicted rows stay visible, grayed.
   - **Trend projection readout:** secondary block (β_i extrapolated podium), visually separated from the headline snapshot.
   - Retained: **Gambit warning banner** whenever any `gambit_flag == 1` (names the Gambit housemates and states their win prob is fixed at 0 under the provisional scenario); Pre/Post-Twist scenario toggle; stale-data badge from `missing_weeks`/`generated_at`; precision label; methodology note stating the cross-blog voter-independence limitation and the weakly-informative prior choice.

---

## 7. Failure points + mitigations

| # | Failure | Mitigation |
|---|---|---|
| 1 | **Missed Saturday / machine off** — the pipeline is human-triggered, so gaps are expected, not exceptional | `preprocess.py` gap-fills missing weeks, flags them in `missing_weeks`; dashboard shows a stale-data badge; no cron means no silent half-runs |
| 2 | **Blog layout drift breaks a parser** | RSS-first ordering (schema-stable); one isolated parser per blog source; per-source try/except with logging — a dead source degrades that week's terms, never kills the run |
| 3 | **Housemate name-alias mismatch across blogs** ("Imisi" vs "Imisioluwa", voting-name vs full name) splits one person's engagement across rows | Canonical `config/housemates.json` alias map (name → aliases + photo filename); unmatched mentions quarantined in a review list printed each Saturday, never silently dropped |

---

## Deliverable map (for `specification.md`, post-approval)

`run_weekly.py` · `config/twist.json` · `config/season.json` (premiere/finale dates drive calendar-true week numbering — added 2026-09-09) · `config/housemates.json` (canonical names, aliases, photo filenames) · `src/scrape_blogs.py` · `src/preprocess.py` · `notebooks/bbnaija_mcmc` (local run record) · `docs/index.html` + `docs/assets/script.js` + `docs/assets/photos/` · `.github/workflows/deploy.yml` (push-triggered, no schedule) · `.env.example` (HF token only) · `tests/` (fixture-based, no network).

> Scope note: **no backtesting, current season only.** Validation is the R-hat < 1.01 gate, in-season week-over-week stability, and eviction concordance as the season progresses.
