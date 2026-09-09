
markdown
# BBNaija 2026 PREDICTOR – AGENT BOOTSTRAP SPECIFICATION

## AGENT ROLE
You are the Lead ML Engineer and DevOps Architect for this project. Your task is to design and build a zero-cost, fully automated predictive analytics pipeline for Big Brother Naija 2026. Using cloud tools tracked on githhub, we have python environments but dont use, rely on cloud for all

## CRITICAL CONSTRAINT
**DO NOT generate any production code yet.** You must first produce `PLAN.md`. Upon approval, produce `specification.md` with all code.

---

## 1. PROJECT GOAL
Build an automated system that scrapes social engagement (Twitter/X + blogs), applies a Bayesian Mixed Model with Model Averaging, and outputs **Win Probabilities** (not raw votes) for all housemates. Deploy results to a static GitHub Pages dashboard that updates every 6 hours during the BBNaija 2026 season. Everything must use 100% free resources.

---

## 2. THE "GAMBIT" TWIST (NON-NEGOTIABLE MODEL CONSTRAINT)
- BBNaija 2026 introduces "The Gambit" twist.
- Viewers vote to select **one male and one female** housemate.
- **Reward**: Immunity from eviction + automatic Grand Finale slot.
- **Punishment**: Permanent disqualification from winning the grand prize.
- **MODELING IMPERATIVE**: The model must explicitly set Win Probability = 0 for any housemate designated as a Gambit. Do not simply lower their probability; mathematically zero it out in the posterior predictive distribution.

---

## 3. 100% FREE TECH STACK (Adhere Strictly)
- **Scraping**: Tweepy (Twitter API v2 free tier – 10k tweets/month) + BeautifulSoup4 for blogs.
- **Sentiment**: VADER (local, unlimited).
- **Heavy Compute (MCMC)**: Google Colab (Free T4 GPU, 12GB RAM).
- **Light Compute (Scraping/Preprocessing)**: GitHub Actions (Free tier: 2,000 min/month for public repos).
- **Modeling**: PyMC + ArviZ.
- **Hosting/Version Control**: GitHub (Public repo) + GitHub Pages.
- **Scheduling**: GitHub Actions Cron trigger (`schedule: '0 */6 * * *'`).

## 4. ARCHITECTURE & DATA FLOW (MUST IMPLEMENT THIS SPLIT)
- **GitHub Actions (Every 6 hours)**:
  1. Scrape Twitter/X for BBNaija hashtags + specific housemate handles.
  2. Scrape designated blog sites for engagement counts.
  3. Compute daily **Conversion Potential Index (CPI)** per housemate:
     `CPI = (0.4 * QuoteTweets) + (0.3 * Replies) + (0.2 * Retweets) + (0.1 * Likes)`
  4. Apply VADER sentiment to classify "eviction sentiment" (negative) vs "save sentiment" (positive).
  5. Commit and push processed CSV/JSON to `data/processed/`.
  
- **Google Colab (Weekly OR On-Demand)**:
  1. Clone the GitHub repo using a Personal Access Token (PAT) stored as a Colab secret.
  2. Install PyMC, ArviZ.
  3. Run MCMC sampling with 4 chains, 2000 draws (ZINB Joint Survival Model).
  4. Apply the "Eligibility Filter" to zero-out Gambit housemates' Win Prob.
  5. Perform Pseudo-BMA+ model averaging across 3 candidate models.
  6. Export `predictions.json` (Median Win %, 89% HDI, Model Weights).
  7. Push `predictions.json` back to the repo using `git` + PAT.

- **FALLBACK MECHANISM**: If Colab fails, GitHub Actions must run a "lite" version (1 chain, 500 draws) to keep the dashboard from going stale.

- **GitHub Pages (Static Frontend)**:
  1. Serve `index.html` and `script.js`.
  2. Fetch `predictions.json` from the raw GitHub URL.
  3. Render a leaderboard with Chart.js (bars + error whiskers for 89% HDI).
  4. Include a toggle switch: "Pre-Twist" vs "Post-Twist" to demonstrate the structural break.

---

## 5. MATHEMATICAL SPECIFICATION (Implement exactly)
### 5.1. ZINB Mixed Model (Count Sub-model)
Linear Predictor:
log(μ_it) = α + α_i + (β + β_i)t + γSentiment_it + δAtRisk_it + θTwist_it + η*(Twist_it * β_i)

Where:

α = global intercept.

α_i = random intercept per housemate (baseline popularity).

β = global slope (time trend).

β_i = random slope per housemate (momentum trajectory).

Sentiment = polarity score from VADER (-1 to 1).

AtRisk = binary indicator (1 if housemate is up for eviction that week).

Twist = binary indicator (1 from the week Gambit is announced onward).

η = interaction term (Twist x Momentum).

text

### 5.2. Survival Sub-model (Eviction Hazard)
- Share the same random intercept `α_i` as a frailty term linked to a Cox Proportional Hazards model. This ensures early evictions inform the model about high-volatility risk profiles.

### 5.3. The Gambit Eligibility Filter (Win Probability Converter)
WinProb_i =
0.0 if GambitFlag_i == 1
exp(μ_i) / sum_{j ∉ Gambit} exp(μ_j) otherwise

text
- Simulate 10,000 draws from a Dirichlet-Multinomial distribution over the eligible housemates to produce the final win probabilities and 89% Highest Density Intervals (HDI).

### 5.4. Model Averaging (BMA)
- **Model 1**: Weighted heavily towards `β_i` (momentum).
- **Model 2**: Weighted heavily towards `α_i` (baseline).
- **Model 3**: Allows `σ²_β` to spike post-Twist (heteroscedasticity).
- **Averaging Method**: Compute Leave-One-Out (LOO) ELPD using ArviZ. Apply Pseudo-BMA+ with bootstrapping. Output the weighted posterior mixture.

---

## 6. AGENT DELIVERABLE #1: `PLAN.md` (Submit this first)
Your `PLAN.md` must contain the following sections:

- **Authentication & Secrets Flow**: Explain how you store `TWITTER_BEARER_TOKEN` and `GITHUB_PAT` in GitHub Secrets, and how Colab retrieves them.
- **GitHub Actions Cron Schedule**: Provide the exact YAML trigger expression and justify why `*/6` hours is optimal for Twitter rate limits.
- **Colab Automation Strategy**: Detail how the Colab notebook will authenticate to GitHub using `gitpython` and the PAT without requiring interactive user input.
- **Rate Limit Contingency**: If Twitter API hits the limit, how does the system fall back to using only blog data for that cycle?
- **Data Schema Definition**: Define the exact JSON structure for `data/processed/daily_cpi.json` and `data/predictions.json`.
- **Risk Analysis**: List 3 specific failure points (e.g., Colab session timeout) and your mitigation strategies.

---

## 7. AGENT DELIVERABLE #2: `specification.md` (Submit after PLAN approval)
Once `PLAN.md` is approved, produce `specification.md` containing the **complete copy-paste-ready code** for:

- `.github/workflows/scrape_and_preprocess.yml` (Full YAML with checkout, Python setup, pip install, script execution, and commit/push steps).
- `src/scrape_twitter.py` (Uses Tweepy v2, handles pagination, applies VADER).
- `src/preprocess.py` (Aggregates raw data into daily CPI, handles housemate mapping).
- `notebooks/bbnaija_mcmc.ipynb` (Google Colab Python script with PyMC model definition, sampling, BMA loop, and `predictions.json` export).
- `docs/index.html` and `docs/assets/script.js` (Static dashboard with Chart.js, the toggle button, and auto-fetch from raw JSON).
- `.env.example` (Template for environment variables).

---

## 8. ENVIRONMENT VARIABLES (Mandatory)
TWITTER_BEARER_TOKEN=your_twitter_v2_bearer_token
GITHUB_PAT=your_github_personal_access_token_with_repo_scope
BBN_HASH_TAGS=bbnaija,bbnaija2026,bbn
HOUSEMATE_HANDLES=housemate1,housemate2,housemate3
RAW_DATA_PATH=data/raw/
PROCESSED_DATA_PATH=data/processed/
PREDICTIONS_PATH=data/predictions.json

text

---

## 9. SUCCESS METRICS (Must achieve all)
- **Convergence**: All R-hat values must be < 1.01 in the MCMC output.
- **Backtesting**: Using historical BBNaija 2024/2025 CPI data, the 89% HDI must successfully contain the actual winner of those seasons.
- **Automation**: The dashboard must update without any manual intervention (cron + Colab auto-push).
- **UI**: The toggle between Pre-Twist and Post-Twist must visibly shift the probabilities, demonstrating the model's structural break logic.

---

## 10. INITIAL INSTRUCTION TO AGENT
**Proceed immediately and output `PLAN.md`.** I will review your architecture and resource allocation before you write any production code.
