# knowledge.md — BBNaija 2026 Predictor

## What this project is
Zero-cost predictive analytics pipeline for Big Brother Naija 2026: scrapes blog/RSS engagement, computes a per-housemate Engagement Index (CPI), runs a local Bayesian MCMC (ZINB joint survival model + 3-model BMA), and outputs **win probabilities** (not raw votes) to a static dashboard (HF Spaces Static primary, GitHub Pages mirror).

## Current status — P2 done, mid-season build week in progress
- **GitHub repo: https://github.com/batestguy/bbnaija2026** (public, `main` tracked). Season 11 is LIVE (premiered 26 Jul 2026, week 7 of ~10 as of 2026-09-09; finale ≈ 4 Oct) → P2–P8 run compressed into one week; first run on Sat Sep 12 is a **backfill run** for weeks 1–6. See `docs/season-recon.md` + the P1 banner in `PHASES.md`.
- **Done:** P0 (approval + fold-in + git init), P1 (season recon — Gambit CONFIRMED: Flora+Aikou wks 1–5, released wk 6 → weekly-varying `gambit_periods` in `config/twist.json`; exit ledger reconciled: wk2 Mercedes+Martins, wk3 Kamsy+Neche-walk, wk4 Cassi, wk5 Sultex+Goddessa, wk6 Gerard → 16 active), P2 (configs, env pins, conventions, scaffold, `.env.example`).
- **Next:** P3 `src/scrape_blogs.py` (+ Wikipedia structured-tables parser candidate), P4 `src/preprocess.py` (backfill-first), P5 modeling, P6 runner, P7 dashboard, P8 deploy — before Sat Sep 12.
- Product definition: **weekly predicted final standings** — each Saturday run publishes the podium projection (winner / runner-up / 2nd runner-up with slot probabilities) plus per-housemate P(#1)/P(top-3)/P(top-5), refreshed continuously as weekly data accrues.
- Files: `AGENTS.md`, `ENVIRONMENTS.md`, `PLAN.md` (approved), `PHASES.md` (lifecycle), `weekly-standings-spec.md` (approved deltas), `docs/season-recon.md`, this file.

## Key corrections to Readme.txt (do not regress)
- **No X/Twitter API anywhere.** Free read tier was removed (Feb 2026). Tweepy, `TWITTER_BEARER_TOKEN`, housemate handles, and Twitter-era rate-limit logic are **dead**. Data is blogs/RSS only: Google News RSS (primary) + BellaNaija/Pulse/DStv via BeautifulSoup4, **one isolated parser per source**.
- **Gambit twist is provisional** (no public record; S10-2025 winner was Imisi). Keep the eligibility-filter math byte-for-byte, but read `GambitFlag`/`Twist` from `config/twist.json` — never hardcode.
- **No cron.** Public-repo Actions minutes are free/unlimited (2,000-min quota is private repos only). Actions is **deploy-only, push-triggered**.
- **Colab is a documented alternative only** — no PAT push-back machinery, no `GITHUB_PAT`.

## Planned architecture (implement this split, nothing else)
`run_weekly.py` → `src/scrape_blogs.py` → `src/preprocess.py` (gap-tolerant; flags `missing_weeks`) → local `notebooks/bbnaija_mcmc` (PyMC + ArviZ) → `data/predictions.json` → push-triggered `.github/workflows/deploy.yml` → HF Space + Dataset repo + Pages mirror.

Specification file list: `run_weekly.py`, `config/twist.json`, `config/housemates.json` (canonical names, aliases, photo filenames), `src/scrape_blogs.py`, `src/preprocess.py`, `notebooks/bbnaija_mcmc`, `docs/index.html`, `docs/assets/script.js`, `docs/assets/photos/`, `.env.example` (HF token only).

Dashboard: trajectory line chart (top-5 medians + 89% CrI bands, photo+name end-labels, dropdown to add housemates) + below-chart panel (pairwise win-prob difference, P(A beats B), likely winner with HDI) + persistent Gambit warning banner + staleness badge + precision label + methodology note.

## Commands
- **No install/dev/test/lint/build exists yet** — no package files. Nothing to run until code is written.
- Planned runtime (Saturday, manual only, ~2 h window): `conda activate bap3` (or `causality-handbook`) → `python run_weekly.py [--lite]` (scrape → backfill-bridge → manual overrides → preprocess → MCMC → standings products → review → push).
- Environments (see `ENVIRONMENTS.md`): `bap3` (Py 3.11, pymc 5.8, arviz 0.16, numpy 1.24) or `causality-handbook` (Py 3.11, pymc 5.25, arviz 0.23, numpy 1.26, pandas 2.3.3). Use `-p <prefix>` for conda on the two prefix envs. Working copy + data live on **D:**; envs on **C:**. Sampling is CPU-bound — no GPU needed.

## Non-negotiable modeling rules
- **Gambit eligibility filter:** `WinProb_i = 0.0` if `GambitFlag_i == 1`, else `exp(μ_i) / Σ_{j ∉ Gambit} exp(μ_j)`. Zero out in **posterior predictive** — never just down-weight.
- **CPI (blog-adapted):** `0.4*Comments + 0.3*Shares + 0.2*ArticleMentions + 0.1*HeadlineFeatures`, min-max normalised per week before weighting; renormalise over available terms and log the renormalisation.
- **Count sub-model:** `log(μ_it) = α + α_i + (β + β_i)t + γSentiment + δAtRisk + θTwist + η(Twist_it·β_i)`; `α_i` shared as frailty in the Cox eviction sub-model.
- **Sampling:** 4 chains × 2000 draws (ZINB joint survival); 10k Dirichlet-Multinomial draws → median + 89% HDI. `--lite` fallback must label `precision` in `predictions.json` — never silently degrade.
- **BMA:** 3 candidates (momentum-heavy / baseline-heavy / post-Twist heteroscedastic `σ²_β` spike); Pseudo-BMA+ via ArviZ LOO ELPD with bootstrapping.
- **Priors are weakly-informative** (revised from the objective set): predictors standardized first; Normal(0, 2.5) fixed effects, HalfNormal(1) variance components, LKJ(2) correlations. No show-history priors. Prior predictive sanity + ~89% posterior predictive coverage are the alarm metrics.
- **Weekly standings machinery:** rank probabilities + podium from the 10k posterior draws (no new sampling); statistical ties on overlapping adjacent HDIs (alphabetical tie-break); secondary β_i trend-projected podium; Gambit housemates P(#1) ≡ 0 but runner-up/top-3/top-5 eligible.
- **Scope:** current season only — **no backtesting**. Convergence gate: reject any run with R-hat ≥ 1.01 (keep last good `predictions.json`, flag staleness).

## Constraints & gotchas
- **$0 ceiling:** no paid service anywhere. Only secret is an HF token for Space sync.
- **Manual-only Saturday runs** (user offline/machines off mid-week). No cron, no local schedulers, **single writer** — never add a scheduled scrape alongside manual runs (dual writers corrupt `data/`).
- **Calendar-true weeks:** `config/season.json` (premiere/finale dates) drives week numbering; missed Saturdays are backfill-bridged from archived scrapes (flagged, never fabricated); mid-week DQs/walkouts are coded as evictions via `data/raw/manual_notes.csv`.
- **Cross-blog voter independence is unverifiable** (same commenters recur across blogs; no $0 dedup key). Treat CPI as a correlated engagement index; state the limitation in README + dashboard methodology note; never claim independent voter sampling.
- Stack: BeautifulSoup4 + RSS, VADER (polarity ∈ [-1,1]), PyMC + ArviZ. `AtRisk`/`Twist` binary. Unmatched housemate aliases get quarantined for review, never silently dropped; missing photos fall back to initials avatars.
- Data schemas (`daily_cpi.json`, `predictions.json`) are pinned in `PLAN.md` §5 — match them exactly.
