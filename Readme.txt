BBNaija 2026 Winner Prediction — Agent Specification (Free-Tier Only)
0. Purpose of This Document
This is a build brief for an agent LLM. It defines what the system does, what is fixed, what is flexible, and what the agent must investigate.

Critical constraint: Every source, tool, and API used must be free tier only. No paid subscriptions, no paid scraping services, no paid API tiers. If a source requires payment or a paid proxy to access reliably, it is excluded. The agent must not assume any budget.

1. System Overview
A weekly-updated model that:

Scrapes free, publicly accessible online polls about BBNaija housemates.

Stores every observation in a single flexible matrix.

Aggregates observations into a support share per active housemate.

Produces a ranked list with bootstrapped 95% intervals.

Renormalises after every eviction.

Tracks momentum week over week.

Incorporates official bottom-N / top-N rankings as constraints.

Output: a clear predicted winner each week, with uncertainty quantified.

2. Fixed: The Data Schema
Every observation — regardless of source or format — is stored as one row in a long-format table. This is the backbone. The agent must not change this schema; it may only add columns.

2.1 Core Columns (Fixed)
Column	Type	Description
obs_id	string	Unique ID
source_name	string	e.g., "BBNaija Daily", "Reddit r/BBNaija"
source_grade	float	A=1.0, B=0.7, C=0.5, D=0.2
obs_type	enum	full_share, bottom_N, top_N, rank
sample_size	int	Actual votes, or pseudo-size for constraints
timestamp	datetime	When the poll/ranking was published
week	int	BBNaija week number
active_set	list[string]	Housemates still in the house at this timestamp
poll_url	string	Source URL for audit
collection_method	enum	html_scrape, api_free, manual_entry
2.2 Housemate Columns (Dynamic)
One column per housemate, named by a canonical housemate ID (lowercase, no spaces). The set of columns grows as new housemates enter and shrinks as they are evicted — but evicted housemates' columns are retained (values NaN for future rows) so historical data remains intact.

For each observation, the value in a housemate's column depends on obs_type:

obs_type	Value	Meaning
full_share	float in [0,1]	Vote share among active housemates
bottom_N	0 or 1	1 = housemate is in the bottom N
top_N	0 or 1	1 = housemate is in the top N
rank	int or NaN	Rank (1 = best), NaN if unranked
2.3 Example Matrix
obs_id	source	obs_type	sample_size	grade	week	active_set	temi	tram	sheba	bluethopia	aikou
001	Blog A	full_share	500	1.0	7	[temi,tram,sheba,bluethopia,aikou]	0.35	0.25	0.20	0.12	0.08
002	Reddit poll	full_share	1200	0.7	7	[temi,tram,sheba,bluethopia,aikou]	0.30	0.28	0.18	0.14	0.10
003	Official	bottom_N	200	1.0	7	[temi,tram,sheba,bluethopia,aikou]	0	0	1	1	1
004	Official	top_N	200	1.0	7	[temi,tram,sheba,bluethopia,aikou]	1	1	0	0	0
005	Telegram bot	full_share	300	0.5	7	[temi,tram,sheba,bluethopia,aikou]	0.28	0.30	0.22	0.10	0.10
Why this is flexible: New observation types are added by adding an enum value and a handler. New sources are added by adding rows. New housemates are added by adding columns. Nothing about the core structure changes.

3. Fixed: The Aggregation Contract
The aggregation pipeline is fixed. The agent must implement exactly this sequence.

3.1 Step 1 — Filter to Active Set and Recent Window
Keep only observations from the last 3 weeks.

For each observation, restrict to housemates in its active_set.

Drop any observation where fewer than 2 active housemates have data.

3.2 Step 2 — Compute Weight for Each Observation
w
k
=
q
k
×
min
⁡
(
n
k
,
cap
)
×
λ
Δ
t
k
w 
k
​
 =q 
k
​
 ×min(n 
k
​
 ,cap)×λ 
Δt 
k
​
 
 
Symbol	Meaning	Default
q
k
q 
k
​
 	Source grade	A=1.0, B=0.7, C=0.5, D=0.2
n
k
n 
k
​
 	Sample size	actual votes, or pseudo-size for constraints
cap
cap	Max effective sample size	5,000
Δ
t
k
Δt 
k
​
 	Age in weeks	—
λ
λ	Recency decay	0.6
3.3 Step 3 — Aggregate Full-Share Observations
Only full_share observations contribute to the base share vector.

For each full_share observation 
k
k:

s
i
,
k
=
v
i
,
k
∑
j
∈
A
t
v
j
,
k
s 
i,k
​
 = 
∑ 
j∈A 
t
​
 
​
 v 
j,k
​
 
v 
i,k
​
 
​
 
Then:

S
i
=
∑
k
∈
full_share
w
k
 
s
i
,
k
∑
k
∈
full_share
w
k
S 
i
​
 = 
∑ 
k∈full_share
​
 w 
k
​
 
∑ 
k∈full_share
​
 w 
k
​
 s 
i,k
​
 
​
 
3.4 Step 4 — Apply Constraint Observations
Constraints (bottom_N, top_N) are applied after the full-share aggregation.

Bottom-N constraint:

Let 
B
B = set of housemates flagged in bottom N.

Let 
m
=
min
⁡
j
∉
B
S
j
m=min 
j∈
/
B
​
 S 
j
​
 .

For each 
i
∈
B
i∈B: 
S
i
←
min
⁡
(
S
i
,
m
×
(
1
−
ϵ
)
)
S 
i
​
 ←min(S 
i
​
 ,m×(1−ϵ)), with 
ϵ
=
0.01
ϵ=0.01.

Renormalise.

Top-N constraint (mirror):

Let 
T
T = set of housemates flagged in top N.

Let 
m
=
max
⁡
j
∉
T
S
j
m=max 
j∈
/
T
​
 S 
j
​
 .

For each 
i
∈
T
i∈T: 
S
i
←
max
⁡
(
S
i
,
m
×
(
1
+
ϵ
)
)
S 
i
​
 ←max(S 
i
​
 ,m×(1+ϵ)).

Renormalise.

Rank observations are converted to shares (see §5.3) and treated as full_share with a small pseudo-sample-size.

3.5 Step 5 — Renormalise
S
i
←
S
i
∑
j
∈
A
t
S
j
S 
i
​
 ← 
∑ 
j∈A 
t
​
 
​
 S 
j
​
 
S 
i
​
 
​
 
3.6 Step 6 — Bootstrap for Uncertainty
For 
b
=
1
b=1 to 
B
=
1000
B=1000:

Resample observations with replacement, probability proportional to 
w
k
w 
k
​
 .

Recompute 
S
i
(
b
)
S 
i
(b)
​
  via Steps 3–5.

Report:

Point estimate: 
S
i
S 
i
​
  from full data.

95% CI: 2.5th and 97.5th percentiles of 
{
S
i
(
b
)
}
{S 
i
(b)
​
 }.

P
(
A
>
B
)
P(A>B): fraction of replicates where 
S
A
(
b
)
>
S
B
(
b
)
S 
A
(b)
​
 >S 
B
(b)
​
 .

3.7 Step 7 — Eviction Renormalisation
When a housemate is evicted:

Remove from active_set.

Set their 
S
S to 0.

Renormalise remaining shares.

This happens before the next week's aggregation.

4. Fixed: The Output Format
Each week, produce a table:

Housemate	
S
i
S 
i
​
 	95% CI	Momentum	P(win)	Rank
Temi Nkem	0.32	[0.26, 0.39]	+0.04	0.41	1
Tram	0.28	[0.22, 0.35]	+0.01	0.29	2
Sheba	0.18	[0.13, 0.24]	−0.02	0.15	3
Bluethopia	0.12	[0.08, 0.17]	−0.01	0.09	4
Aikou	0.10	[0.06, 0.15]	−0.02	0.06	5
Decision rules:

P
(
A
>
B
)
>
0.90
P(A>B)>0.90: clear lead

0.60
<
P
(
A
>
B
)
<
0.90
0.60<P(A>B)<0.90: leaning, not decisive

P
(
A
>
B
)
<
0.60
P(A>B)<0.60: too close to call

Also store the full time series of 
S
i
S 
i
​
  per housemate for trend plots.

5. Flexible: Sources, Extensions, and Parameters
5.1 Sources — Free Tier Only
The agent must investigate and catalog only free, publicly accessible sources. Anything requiring a paid API, paid proxy, or paid scraper is excluded.

Viable free sources (in priority order):

Tier	Source type	Grade	Access method	Notes
1	Official BBNaija bottom-N / top-N	A (1.0)	Scrape news blogs reporting it	Pseudo-size 200
2	Blog polls with visible vote counts	A (1.0)	requests + BeautifulSoup or Playwright	Actual sample size
3	Reddit polls (r/BBNaija and related)	B (0.7)	PRAW (free)	Actual sample size
4	Telegram polls in public groups	B (0.7)	Telethon / python-telegram-bot (free)	Only if bot is a member
5	Google Forms fan polls (public)	C (0.5)	HTML scrape	If shared publicly
6	Nairaland polls / threads	C (0.5)	HTML scrape	Low structure
7	YouTube comments (not community polls)	D (0.2)	YouTube Data API v3 free quota	Sentiment only
8	Facebook group polls	D (0.2)	Manual entry	No free API
Excluded free-tier gaps (document these):

Twitter/X polls: Free tier of X API does not expose poll data. Nitter instances are largely defunct. Do not attempt automated Twitter scraping. If a volunteer manually records a Twitter poll, enter it via manual_entry with grade B.

Instagram story polls: No free reliable access. Exclude.

WhatsApp polls: No free API. Manual entry only if a volunteer exports.

YouTube community polls: Not exposed by YouTube Data API v3. Free scraping via Playwright is possible but brittle; treat as optional Tier 6 (grade C) if it works.

Apify / paid scrapers: Excluded.

Rules:

Never scrape login-gated or CAPTCHA-protected sources.

Always respect robots.txt.

Log every source's URL, timestamp, and raw values for audit.

Mark collection_method for every row so provenance is clear.

5.2 New Observation Types
The agent may add new obs_type values (e.g., head_of_house, most_nominated) provided:

A handler converts the observation into either a share contribution or a constraint.

The handler is documented.

The new type does not break the core aggregation contract.

5.3 Rank-to-Share Conversion
If a source provides a ranking without shares:

s
i
,
k
=
1
/
rank
i
∑
j
∈
A
t
1
/
rank
j
s 
i,k
​
 = 
∑ 
j∈A 
t
​
 
​
 1/rank 
j
​
 
1/rank 
i
​
 
​
 
Assign sample_size = 50, grade = C (0.5). Treat as full_share.

5.4 Tunable Parameters
Parameter	Default	Range	Effect
cap	5000	1000–20000	Max effective sample size per poll
λ	0.6	0.3–0.9	Recency decay; lower = faster
ε	0.01	0.001–0.05	Constraint margin
pseudo_n_constraint	200	50–1000	Bottom-N pseudo-size
window_weeks	3	2–5	How many weeks of polls to use
B	1000	500–5000	Bootstrap replicates
q_grades	A=1.0, B=0.7, C=0.5, D=0.2	—	Source quality
All parameters must be stored in a single config file.

5.5 Platform-Specific Handling (Free Tier)
Blog polls: requests + BeautifulSoup, or Playwright (free, open source) for JS-rendered polls. Extract question, options, vote counts/percentages, timestamp.

Reddit polls: PRAW (free) with a registered script app. Poll data is accessible via the Reddit API free tier.

Telegram: python-telegram-bot or Telethon (free). Only works if your bot is in the group and the poll is visible.

Google Forms: HTML scrape of the public results page if shared.

Nairaland: HTML scrape. Low structure; parse carefully.

YouTube comments: YouTube Data API v3 free quota (10,000 units/day). Community polls are not exposed; comments only. Treat as weak sentiment.

Manual entry: For Twitter, WhatsApp, Facebook, or any source a volunteer transcribes. Set collection_method = manual_entry.

The agent must write a separate adapter per source, each returning rows conforming to the schema in §2. Adapters that cannot run on free tier must be documented as excluded, not silently skipped.

6. Flexible: Back-Testing and Tuning
The agent must:

Collect historical poll data for at least one past season (e.g., Season 9 or 10) from free sources (blog archives, Reddit threads, news articles).

Run the pipeline week by week.

Compare predicted bottom-N and predicted winner to official eviction results.

Tune cap, λ, ε, pseudo_n_constraint, and source grades to minimise error.

Document the tuning results.

If historical poll data is unavailable on free tier, the agent should note this and proceed with defaults.

7. Implementation Checklist for the Agent
Phase 1 — Investigation
□ Confirm the free-tier-only constraint applies to every tool and source.
□ Identify all currently active BBNaija 2026 poll sources accessible on free tier.
□ Verify access method (free API, free scrape, manual) for each.
□ Check robots.txt and terms of service for each source.
□ Confirm housemate canonical IDs and active set.
□ Locate official bottom-N / top-N release schedule (news blogs, official social posts).
□ Locate historical poll data for back-testing on free tier (if available).
□ Explicitly document which sources are excluded due to paid-tier requirements (Twitter/X API, Instagram, Apify, etc.).
Phase 2 — Build
□ Implement the long-format matrix (§2).
□ Write one free-tier adapter per source (§5.5).
□ Implement weight computation (§3.2).
□ Implement full-share aggregation (§3.3).
□ Implement constraint application (§3.4).
□ Implement renormalisation (§3.5).
□ Implement bootstrap (§3.6).
□ Implement eviction handling (§3.7).
□ Implement output table (§4).
Phase 3 — Validate
□ Back-test on past season(s) using free-tier historical data.
□ Tune parameters (§5.4).
□ Document tuning results.
□ Produce a sample weekly report.
Phase 4 — Operate
□ Schedule weekly run (Sunday morning, before eviction show).
□ Log every run's inputs and outputs.
□ Publish weekly report with clear "fan forecast, not official result" disclaimer.
□ Re-check source availability each week (free sources go down or change format).
8. Summary of What Is Fixed vs. Flexible
Component	Status
Long-format matrix schema	Fixed
obs_type enum values	Flexible (add allowed)
Aggregation sequence	Fixed
Weight formula	Fixed (parameters tunable)
Constraint logic	Fixed
Bootstrap procedure	Fixed
Eviction renormalisation	Fixed
Output table columns	Fixed
Free-tier-only constraint	Fixed
Sources	Flexible (free tier only)
Source grades	Flexible (tunable)
Adapters	Flexible (one per free source)
Tunable parameters	Flexible (in config)
New observation types	Flexible (with handler)
The agent may extend anything in the "Flexible" column. Everything in the "Fixed" column must remain as specified to preserve the aggregation contract and ensure clean, correct, sample-size-aware aggregation across all current and future free-tier polls.