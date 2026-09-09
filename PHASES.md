# PHASES.md — BBNaija 2026 Predictor: Full Project Lifecycle

> **Purpose:** one ordered phase plan, beginning to end, turning `PLAN.md` + `weekly-standings-spec.md` into shippable increments. Each phase has verifiable exit criteria; no phase starts before its entry criteria hold.
> **Status:** proposed execution plan. Writing production code still requires the Phase 0 approval gate.
> **Sources of truth:** `PLAN.md` (architecture, math, deploy) · `weekly-standings-spec.md` (weekly standings, podium, priors deltas — referred to as "the spec") · `AGENTS.md` (non-negotiables) · `ENVIRONMENTS.md` (local envs).

> **⚠ SEASON STATUS UPDATE (P1 recon, 2026-09-09 — see `docs/season-recon.md`):** Season 11 is **LIVE** — premiered 26 Jul 2026, currently week 7 of ~10, finale ≈ 4 Oct. Consequences:
> 1. **Backfill-first:** weeks 1–6 must be reconstructed from archives (RSS history, Wikipedia structured tables, blog recaps) before any live prediction publishes. P4.4's bridge is now the *first-run* path, not a fallback.
> 2. **Compressed schedule:** P2–P8 must complete in one week (before Sat Sep 12). P9's rehearsal merges into the first live run: rehearse with weeks 1–6 data, then publish week 7 from the same session.
> 3. **Twist.json schema upgrade:** the Gambit is CONFIRMED (Flora + Aikou, weeks 1–5, released via "Operation Release the Gambit" on Aug 30). `gambit_flag` is weekly-varying → per-housemate week ranges in config (P2.3 revision).
> 4. **P10 runs at standard cadence** immediately after the compressed build week; P11 closeout lands ~Oct 4.

---

## 0. Lifecycle map

```
P0 Approvals ──► P1 Season Recon ──► P2 Repo Scaffold ──► P3 Data Acquisition ──► P4 Preprocessing
                                                                                        │
                     ┌──────────────────────────────────────────────────────────────────┘
                     ▼
              P5 Modeling Core ──► P6 Weekly Runner ──► P7 Dashboard ──► P8 Deploy Pipeline
                                                                                        │
                     ┌──────────────────────────────────────────────────────────────────┘
                     ▼
              P9 Preseason Rehearsal ──► P10 Season Operations ──► P11 Season Closeout
```

Phases P2–P8 are **build phases** (can overlap lightly, but exit in order). P9 is the go/no-go rehearsal. P10 is the live loop. P11 closes the season.

**Season-status routing:** the outcome of P1 decides variants inside later phases — see §R at the bottom. If S11 is postponed/absent, P10 is replaced by P10-alt (scenario/demo mode) and the project still completes.

---

## P0 — Approval Gate (beginning)

**Objective:** obtain explicit user approval for everything the build will implement.

| Task | Detail |
|---|---|
| P0.1 | Present `PLAN.md` for approval (it is still marked *awaiting approval*) |
| P0.2 | Present `weekly-standings-spec.md` deltas for approval (podium ranking, weakly-informative priors, `config/season.json`, backfill-bridge, DQ-as-eviction) |
| P0.3 | On approval: fold spec deltas into `PLAN.md` (§4 priors, §5 schemas, §6 dashboard/workflow, file list gains `config/season.json`), update `AGENTS.md` modeling rules + `knowledge.md`, and mark both docs **approved** |
| P0.4 | Init the git repo (first commit: docs only) |

**Exit criteria:** user says "approved"; `PLAN.md` no longer says awaiting-approval; repo is a git repo with one docs commit.
**Guardrail:** nothing in P1–P11 starts until this gate passes. If the user requests changes, they land in the docs first, then re-approval.

---

## P1 — Season Status Reconnaissance (highest uncertainty, do first)

**Objective:** replace provisional assumptions with verified facts about BBNaija Season 11 (2026) — this determines config content, week numbering, and whether the twist exists.

| Task | Detail |
|---|---|
| P1.1 | Verify S11 is confirmed: premiere date, season length (~10 weeks precedent), finale date |
| P1.2 | Collect the official housemate roster as names are revealed (canonical names + known aliases + photo sources) |
| P1.3 | Investigate any announced twist (the "Gambit" remains **provisional** until a credible source confirms it — S10 had no Gambit on record) |
| P1.4 | Verify the data sources are live and scrapeable: Google News RSS per housemate-name query; BellaNaija / Pulse Nigeria / DStv Africa Magic tag pages; note which expose comments/shares counts |
| P1.5 | Record findings in a short `docs/season-recon.md` note (source URLs, dates, confidence) |

**Exit criteria:** `season.json` inputs are either real dates or explicitly-labeled placeholders; roster ≥ partially known or a fill-in plan exists; each blog source has a one-paragraph scrapeability verdict.
**Constraint:** research only — no code, no scraping scripts yet. All findings cited.

---

## P2 — Repo Scaffold

**Objective:** create the exact file skeleton from `PLAN.md`'s file list (+ spec additions), so every later phase drops into place.

| Task | Detail |
|---|---|
| P2.1 | Create structure: `src/`, `notebooks/`, `data/raw/`, `data/processed/`, `config/`, `docs/assets/photos/`, `.github/workflows/`, `tests/` |
| P2.2 | Write `config/housemates.json` (from P1 roster; entry weeks; alias map; photo filenames — initials-avatar fallbacks documented for missing photos) |
| P2.3 | Write `config/twist.json` (provisional: `gambit_housemates: []`, `twist_start_week: null`) and `config/season.json` (P1 dates or placeholders) |
| P2.4 | Write `.env.example` (HF token only — the single secret; no `GITHUB_PAT`, no `TWITTER_BEARER_TOKEN`, ever) |
| P2.5 | Write `.gitignore` (`data/raw/*` contents except `manual_notes.csv` template, `.env`, `__pycache__/`, notebook checkpoints) |
| P2.6 | Pin the working environment: `bap3` (pymc 5.8 / arviz 0.16 / numpy 1.24) as primary, `causality-handbook` (pymc 5.25) as fallback; record `conda env export` snapshots in `docs/envs/`; working copy + `data/` live on **D:** |
| P2.7 | Choose and record code conventions (formatter, type hints on/off, log format) — keep minimal |

**Exit criteria:** skeleton committed; both configs parse as JSON; `python -c "import json; ..."` sanity check passes; env snapshots documented.
**Constraint:** config files only — no executable code yet.

---

## P3 — Data Acquisition Layer (`src/scrape_blogs.py`)

**Objective:** reliable, polite, isolated per-source scrapers producing raw weekly engagement records — the only phase that touches the outside world.

| Task | Detail |
|---|---|
| P3.1 | Google News RSS client (primary): per-housemate query builder (`name + BBNaija`), stable record schema, rate-limit-friendly pacing |
| P3.2 | One **isolated parser per blog source** (BellaNaija, Pulse, DStv): each in its own function/class with its own try/except + logging — a layout change breaks one source, never the run |
| P3.3 | Term extraction per source: comments/shares where exposed; `article_mentions` always; `headline_features` when the name is in the headline |
| P3.4 | VADER sentiment on headlines + first paragraphs (polarity ∈ [-1, 1]) at scrape time |
| P3.5 | Alias resolution against `config/housemates.json`; unmatched mentions → **quarantine list** (printed + logged, never silently dropped) |
| P3.6 | `data/raw/manual_notes.csv` loader: DQ/walkout overrides, corrections (this is the D11 channel) |
| P3.7 | Archive policy: every scrape writes raw snapshots by week so the backfill-bridge (P4.4) can re-read old weeks |
| P3.8 | Unit tests with fixture HTML/RSS files (no network in tests) |

**Exit criteria:** `pytest tests/` green; a manual smoke scrape of one week against live sources produces well-formed raw records for every configured source; quarantine + logging demonstrated.
**Constraints:** $0 (no keys); **no X/Twitter anywhere**; single writer discipline established from day one (no scheduled scrapes, ever).

---

## P4 — Preprocessing & Season Calendar (`src/preprocess.py`)

**Objective:** turn raw scrape snapshots into the model-ready weekly table with gap tolerance.

| Task | Detail |
|---|---|
| P4.1 | Week numbering from `config/season.json` (premiere → finale calendar weeks); runs never renumber weeks |
| P4.2 | Weekly CPI: `0.4*Comments + 0.3*Shares + 0.2*ArticleMentions + 0.1*HeadlineFeatures`, min-max normalised per week before weighting; **renormalise over available terms and log the renormalisation** |
| P4.3 | `AtRisk` coding from nomination/show-report posts (varies weekly); `Twist`/`GambitFlag` read only from `config/twist.json` |
| P4.4 | **Backfill-bridge:** missing previous week → rebuild from P3.7 archives, mark `backfilled: true`, append to `backfilled_weeks`; if archives can't cover it, leave the gap + `missing_weeks` flag (never fabricate counts) |
| P4.5 | DQ/walkout coding: manual-note evictions → `status: disqualified`, `evicted_week: N`, `dq_source: manual_notes` |
| P4.6 | Output `data/processed/daily_cpi.json` exactly per the spec §5 schema (one record per housemate-week; `sources` array; `missing_weeks`) |
| P4.7 | Gap-tolerant tests: missing week, mid-season DQ, entry-week housemate (pre-entry = missing, not zero) |

**Exit criteria:** tests green; one end-to-end dry preprocess from P3 smoke data yields a schema-valid `daily_cpi.json` (validated against a small JSON-schema check added in this phase).

---

## P5 — Modeling Core (`notebooks/bbnaija_mcmc`)

**Objective:** the PyMC model, Gambit filter, ranking/podium machinery, and BMA — built and tested **before** integration, with synthetic data.

| Task | Detail |
|---|---|
| P5.1 | Standardization layer for predictors (`t`, sentiment z-scored; `AtRisk`/`Twist` binary); store means/scales in the run record |
| P5.2 | Count sub-model exactly: `log(μ_it) = α + α_i + (β + β_i)t + γSentiment + δAtRisk + θTwist + η(Twist_it·β_i)` |
| P5.3 | **Weakly-informative priors** (spec): Normal(0, 2.5) fixed effects · HalfNormal(1) variance components · LKJ(2) correlations; no show-history priors; every prior printed to the run log |
| P5.4 | Cox eviction sub-model sharing `α_i` as frailty; relative hazards only (no absolute % machinery) |
| P5.5 | **Gambit eligibility filter, byte-for-byte:** `WinProb_i = 0.0` if `GambitFlag_i == 1`, else `exp(μ_i) / Σ_{j ∉ Gambit} exp(μ_j)` — zeroed in posterior predictive, never down-weighted; Gambit housemates stay runner-up-eligible (P(#1) ≡ 0, P(top-3/top-5) live) |
| P5.6 | 10k Dirichlet-Multinomial posterior predictive draws → medians + 89% HDI → **rank machinery**: `p_rank_1`, `p_top3`, `p_top5`, podium slots with slot probabilities, statistical-tie detection (overlapping adjacent HDIs), deterministic alphabetical tie-break |
| P5.7 | **Trend projection:** per-draw β_i momentum extrapolation to `t_finale` with horizon-scaled uncertainty; produces the *secondary* projected podium, never merged into the headline snapshot |
| P5.8 | BMA: 3 candidates (momentum-heavy / baseline-heavy / post-Twist σ²_β spike), Pseudo-BMA+ via ArviZ LOO ELPD with bootstrapping |
| P5.9 | Sampling config: 4 chains × 2000 draws; fixed seeds; convergence gate **R-hat < 1.01 else reject** (keep last good output, flag stale); `--lite` mode labels `precision: "lite"`, never silently |
| P5.10 | Tests on synthetic data: Gambit zero-out, rank probs sum correctly, tie-break determinism, prior-predictive sanity (plausible season shapes, no 0%/100% pathologies), R-hat gate behavior on a deliberately bad run |

**Exit criteria:** all tests green; one full synthetic-data sampling run completes inside the Saturday budget (~30–60 min CPU) with R-hat < 1.01 and zero divergences; run record (seeds, priors, standardization params) written.
**Constraint:** pure modeling — no I/O coupling to scraping, no dashboard yet.

---

## P6 — Weekly Runner Integration (`run_weekly.py`)

**Objective:** the single entrypoint stitching P3→P5 into the one-command Saturday workflow.

```
python run_weekly.py [--lite] [--week N]
```

| Task | Detail |
|---|---|
| P6.1 | Orchestrate: load configs → scrape → backfill-bridge → manual overrides → preprocess → MCMC → posterior products → write `data/predictions.json` |
| P6.2 | Write `predictions.json` exactly per spec §5.2: podium, trend_projection, at_risk (relative hazards, nominated-only), per-housemate `status`/`final_place`/rank probs/`history` append, `priors` audit block, `precision`, `rhat_max`, `missing_weeks`, `backfilled_weeks` |
| P6.3 | Gates in order: schema validation → R-hat gate → write. Rejected run **keeps the last good file** and flags staleness |
| P6.4 | Console review summary: podium with slot probs, implied rank changes, at-risk ranking, convergence + coverage stats, quarantine list — the human decides to push |
| P6.5 | Timing instrumentation per stage (scrape / preprocess / sampling) against the ~2 h Saturday budget |

**Exit criteria:** one full command run on real P3/P4 data produces a schema-valid `predictions.json` end-to-end within budget; `--lite` demonstrably labels precision; gate rejection demonstrated once on a doctored run.

---

## P7 — Dashboard (`docs/index.html` + `docs/assets/script.js`)

**Objective:** the static frontend per PLAN §6 + spec §6 deltas. Chart.js, fetched JSON, zero backend.

| Task | Detail |
|---|---|
| P7.1 | **Trajectory line chart** (unchanged core): top-5 medians + 89% CrI bands, photo+name end-labels, dropdown to add any housemate; missing photos → initials avatars |
| P7.2 | **Podium strip:** projected winner / runner-up / 2nd runner-up with slot probabilities; Gambit names allowed in 2nd/3rd, cross-referenced with the banner (P(#1) = 0) |
| P7.3 | **Rank-probability chips:** P(#1) · P(top-3) · P(top-5) per row |
| P7.4 | **Statistical-tie markers** between adjacent overlapping HDIs |
| P7.5 | **At-risk panel:** nominated housemates ranked by relative hazard, explicitly labeled *relative* |
| P7.6 | **Status badges:** evicted wk N / disqualified wk N / final place once known; evicted rows stay visible, grayed |
| P7.7 | **Trend projection readout:** secondary block, visually separated from the headline snapshot |
| P7.8 | **Persistent elements:** Gambit warning banner (when any `gambit_flag == 1`), Pre/Post-Twist scenario toggle labeled "(provisional)", stale-data badge, precision label, methodology note (weakly-informative priors + cross-blog correlated-index limitation) |
| P7.9 | Graceful degradation: absent fields (e.g. no `trend_projection`) hide their block — never render broken UI |
| P7.10 | UI geometry checks: no overlaps/covering at common viewport widths (fetched-data edge cases: 2 housemates, 29 housemates, long names) |

**Exit criteria:** dashboard renders the P6 output correctly at all edge-data sizes; geometry check passes; every dashboard claim traceable to a JSON field.

---

## P8 — Deploy Pipeline (`.github/workflows/deploy.yml`)

**Objective:** push-triggered deploy-only automation across the three $0 surfaces.

| Task | Detail |
|---|---|
| P8.1 | Workflow triggers **on push only — no schedule, no cron** (public-repo Actions free; single-writer rule preserved) |
| P8.2 | Validate `predictions.json` against the schema as CI step 1 (bad file fails the deploy, last good file stays live) |
| P8.3 | Sync JSON to the HF Dataset repo; HF Space (Static) rebuilds; GitHub Pages mirrors the same commit |
| P8.4 | Secret: **HF token only**, stored as a GitHub secret + `.env` locally; nothing else |
| P8.5 | Cold-start insurance: README pins screenshots + a demo GIF (HF Spaces idle-sleep; Pages does not — the two URLs cover each other) |

**Exit criteria:** a test push propagates to all three surfaces; an intentionally invalid `predictions.json` blocks the deploy; zero other secrets in the repo.

---

## P9 — Preseason Rehearsal (go/no-go)

**Objective:** prove the whole loop before real predictions matter.

| Task | Detail |
|---|---|
| P9.1 | **Dry run with synthetic-but-plausible data** (generated from the real config roster): full `run_weekly.py` → dashboard → deploy path exercised |
| P9.2 | Prior/posterior predictive coverage check passes (~89% coverage on synthetic truth) |
| P9.3 | **Timing rehearsal:** full run timed within the ~2 h Saturday window, including human review; `--lite` fallback timed too |
| P9.4 | Failure drills: kill sampling mid-run (lite recovery + staleness flag); dead blog source (degraded-but-green run); missed-week bridge drill |
| P9.5 | Dashboard review on the deployed rehearsal output (all panels, both scenarios, banner logic) |
| P9.6 | Go/no-go checklist signed off; fix-forward any failures and re-rehearse the failed drill only |

**Exit criteria:** checklist 100% green; the deployed rehearsal URL is viewable on a phone; the loop is proven end-to-end.

---

## P10 — Season Operations (the live weekly loop)

**Objective:** run the product for the ~10-week season. **Manual-only Saturdays** — no cron, no schedulers, single writer.

| Task | Detail |
|---|---|
| P10.1 | **Weekly ritual (every Saturday, ~2 h):** `git pull` → `python run_weekly.py` (or `--lite` if short) → review console summary → `git push` → verify dashboard |
| P10.2 | **Week-3 checkpoint:** review HDI widths + coverage + eviction concordance; document whether priors/standardization are behaving; any change requires a committed note + re-run (no silent retuning) |
| P10.3 | **Mid-season twist switch:** if the real twist is confirmed, update `config/twist.json` only (model code frozen); toggle label drops "(provisional)"; banner behavior per spec |
| P10.4 | **Weekly hygiene:** quarantine list reviewed; `manual_notes.csv` entries for any mid-week DQ/walkout; roster additions get entry-week rows |
| P10.5 | **Concordance tracking:** at-risk top pick vs actual Sunday eviction, logged weekly; podium churn logged |
| P10.6 | **Staleness insurance:** a missed Saturday is handled next week by the backfill-bridge; if >2 weeks are missed, publish an honest stale banner and rebuild from archives |

**Exit criteria:** `predictions.json` exists and is schema-valid for every season week (bridge-labeled where backfilled); concordance + churn log complete.

**P10-alt (season absent/postponed):** run the loop in **scenario/demo mode** against `config/season.json` placeholder dates with clearly-labeled synthetic data — ships the portfolio product without claiming live prediction. Dashboard banner states scenario mode explicitly.

---

## P11 — Season Closeout

**Objective:** end the season cleanly and bank the portfolio value.

| Task | Detail |
|---|---|
| P11.1 | Finale Sunday: real results replace projections; final `predictions.json` archived (read-only); dashboard flips to **final standings** mode with actual final places |
| P11.2 | Season report: calibration summary (coverage), eviction concordance rate, podium accuracy (was the winner in the projected podium? at which week did the projection lock on?), BMA weight evolution |
| P11.3 | Post-mortem: what the weakly-informative priors did vs the objective set (documented, not retconned); bridge/gap statistics; scraper mortality |
| P11.4 | Repo hygiene: tag the final release; README updated with results + screenshots + demo GIF; archive model run records |

**Exit criteria:** final standings published; report committed; repo is portfolio-ready.

---

## Cross-phase constraints (enforced everywhere)

1. **$0 ceiling** — no paid service anywhere; only secret: HF token.
2. **No X/Twitter** — blogs/RSS only; Tweepy/bearer tokens must never appear in code, configs, or docs.
3. **Manual-only Saturdays** — no cron/scheduler, single writer; nothing scrapes outside the Saturday run.
4. **Gambit math frozen** — filter stays byte-for-byte; twist details live only in `config/twist.json`.
5. **Honesty gates** — R-hat < 1.01 else reject+stale; `--lite` always labeled; no claim of independent voter sampling; interval-first presentation; precision label everywhere.
6. **Local-first** — sampling on C: envs (`bap3` primary), working copy + data on D:; Colab documented alternative only, no PAT push-back.
7. **Current season only** — no backtesting, no show-history priors.

## Risk register (from PLAN §7, phase-mapped)

| Risk | Phases | Mitigation lives in |
|---|---|---|
| Missed Saturday / machine off | P10 | Backfill-bridge (P4.4), stale banner (P7.8), gap-tolerant preprocess |
| Blog layout drift | P3, P10 | Isolated per-source parsers, per-source try/except, RSS-first |
| Alias/name mismatch | P3, P10 | Canonical alias map + quarantine list, never silent drops |
| Cold-start overconfidence | P5, P9 | Weakly-informative priors, prior predictive sanity, coverage check |
| Sampler rejects a live week | P5, P6, P10 | Keep-last-good + staleness flag; `--lite` recovery drill (P9.4) |
| Twist unconfirmed | P1, P10 | Provisional config + labeled scenario toggle; P10-alt if season absent |
