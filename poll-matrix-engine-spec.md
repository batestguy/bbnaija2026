# poll-matrix-engine-spec.md — BBNaija 2026 Poll-Matrix Engine Overhaul

**Date:** 2026-09-22
**Status:** APPROVED-BY-INTERVIEW (owner decisions 2026-09-22, recorded in §12 Decision Log)
**Supersedes:** `Readme.txt` as the canonical build brief. `Readme.txt` is retained as **historical reference only** — its §2 (schema), §3 (aggregation contract), §4 (output format) are the design basis, but where this spec differs, **this spec wins**.
**Also supersedes (partially):** the 2026-09-20 poll-anchored-prior decision (`knowledge.md`, `AGENTS.md`, `docs/polls-runbook.md`) — the weak alpha-shift anchor is retired along with the MCMC it fed.
**Does NOT touch:** `PLAN.md`/`PHASES.md` history, git history, or the deploy topology (push-triggered Actions → GitHub Pages primary + HF mirror).

---

## 1. Goal and motivation

Replace the blog-CPI → PyMC MCMC → BMA engine with the **poll-matrix engine** designed in `Readme.txt` (long-format observation matrix → weighted aggregation → constraints → bootstrap), as the **only** model, **live this season** — first certified run **Saturday 2026-09-26**.

**Why:** the accuracy gap. The MCMC's podium contradicted what fans see in polls — Chimsom Chuka P(#1)=0.365 while fans had her dead last (5.31%); Temi Nkem's coverage collapse (CPI 0.0 in wk7–8) sank her to 0.040 despite poll support. Root cause: CPI is effectively *weekly article mentions only* (comments/shares always null, headline features collinear). The owner trusts fan vote signal; polls must become the engine, not an anchor.

**Success looks like:** the Sep 26 predicted standings are computed from aggregated fan-poll shares, are explainable by hand (share = P(win)), and weekly concordance vs actual evictions accumulates as evidence through the Oct 4 finale.

## 2. Non-negotiable constraints (inherited, unchanged)

- **$0 ceiling.** No paid service anywhere. Only secret remains the HF token for Space sync.
- **Manual-only Saturday runs, single writer.** The engine runs inside `run_weekly.py` — no cron, no local schedulers, no second scheduled scrape. Dual writers corrupt `data/`.
- **No X/Twitter API, ever.** Twitter/Instagram/WhatsApp remain documented exclusions (manual entry only if a volunteer transcribes).
- **Calendar-true weeks** from `config/season.json`; mid-week DQ/walkout coded as eviction via `data/raw/manual_notes.csv`; missing weeks flagged, never fabricated.
- **Canonical names/aliases** from `config/housemates.json`; unmatched poll labels are **quarantined** for review, never silently dropped.
- **Gambit twist is provisional**; `GambitFlag`/`Twist` timing read from `config/twist.json`, never hardcoded.
- **Deploy is push-triggered, schema-gate-first** — the gate in `products_schema.py` + `.github/workflows/deploy.yml` must be updated in the same change as the output schema (§9).
- **"Fan forecast, not official result" disclaimer** on every published surface.

## 3. Architecture (new run path)

```
run_weekly.py
  → src/scrape_polls.py      (Sat fetch: bbnaijadaily widget + ngnews247 RSS; archive raw HTML)
  → src/poll_matrix.py       (NEW: build/update the long-format matrix — dedupe, seed rows, carry-forward)
  → src/aggregate.py         (NEW: weights → full-share aggregation → softened constraints → renormalize → bootstrap)
  → src/products.py          (NEW or refactored: podium, chips, pairwise, momentum, ties from replicates)
  → schema gate (products_schema.py, updated)
  → console review → docs/predictions.json → owner pushes → deploy workflow
```

- Matrix persisted at `data/poll_matrix.csv` (long format, §4) + archived weekly snapshots under `data/raw/week_XX/` as today.
- `docs/polls.json` remains the human-visible poll log (manual FB rows, transcription notes, auto-scrape provenance).
- MCMC pipeline is **retired in place** (§10); `notebooks/bbnaija_mcmc.py`, `.mcmc_*` dirs, and MCMC-only modules stay in the repo untouched but leave the run path.

## 4. Data schema — the long-format matrix (Readme §2, with additions)

One row per observation; core columns fixed; one column per canonical housemate ID (evicted columns retained, NaN forward). Housemate column semantics by `obs_type` exactly per Readme §2.2 (`full_share` = float share; `bottom_N`/`top_N` = 0/1 flags; `rank` = int or NaN).

**Added columns (the spec permits adding columns):**

| Column | Type | Purpose |
|---|---|---|
| `snapshot_id` | string | Ties a row to its source snapshot file for audit |
| `n_collapsed` | int | How many same-source-week snapshots were collapsed into this row by the latest-wins rule (§5.1) |
| `provenance` | enum | `live_scrape` \| `transcribed_seed` \| `manual_entry` \| `reparse` |
| `carried` | bool | Row contributed only covered housemates this week (drives carry-forward flagging, §5.4) |

## 5. Aggregation contract (Readme §3 sequence, frozen, with decided deltas)

The sequence is fixed: **filter → weight → aggregate full-share → apply constraints → renormalize → bootstrap → eviction renormalize.** Parameters live in a single config (`config/poll_engine.json`).

### 5.1 Filter & dedupe (delta: latest-wins)
- Keep observations in the last `window_weeks = 3` weeks; restrict each row to its `active_set`; drop rows with <2 active housemates with data.
- **Latest-wins dedupe:** all snapshots from one source in the same week collapse into **one** matrix row — the most recent snapshot wins (`n_collapsed` records how many). Midweek probes no longer exist as a recurring practice (§8), so this mainly governs seed rows, reparse recoveries, and any manual re-runs.

### 5.2 Weights (Readme §3.2, unchanged)
`w_k = q_k × min(n_k, cap) × λ^Δt_k` with `q` grades per §7, `cap = 5000`, `λ = 0.6`.

**Cap posture (decided):** `cap = 5000` stands even though bbnaijadaily's real totals are ~600k votes/week. The widget counts as a large-but-not-infinite poll; manual rows and constraints keep real influence. Raising/removing the cap is a P11 decision with season evidence.

### 5.3 Full-share aggregation (Readme §3.3, unchanged)
Per-observation shares renormalized over the row's covered active set; `S_i = Σ w_k·s_i,k / Σ w_k` over full_share rows only.

### 5.4 Poll-scope gap (delta: carry-forward)
The bbnaijadaily poll covers only the week's **nominated** housemates some weeks (wk-7 manual row: "all 13 nominated"). Non-nominated actives have no votes that week:
- Covered housemates aggregate as usual.
- **Uncovered actives inherit last week's aggregated share** before the weekly renormalization, flagged `carried = true` in output for audit.
- Never fabricate poll numbers for uncovered housemates — the carried value is explicitly a carry, labeled in the run review.

### 5.5 Constraints (Readme §3.4, delta: soften-on-conflict)
- Official bottom-N: `S_i ← min(S_i, m×(1−ε))`, ε=0.01, for flagged i; top-N mirror; renormalize after each.
- **Soften-on-conflict:** if the constraint's implied ordering contradicts the aggregate's ordering (e.g., a bottom-N-flagged housemate already ranks above the cap threshold in polls), pull the affected shares **halfway** toward the constraint bound instead of full cap/floor. Full application when the constraint agrees with the aggregate's ordering. Every softened application is logged with before/after shares.
- ngnews247 titles become **top_N=2 constraint rows** (grade C, pseudo-n=50): floor the two named leaders just above the max non-leader share, subject to soften-on-conflict. Rank-only titles never become shares.
- **Official bottom-N/top-N adapter** (grade A, pseudo-n=200, scraped from news blogs reporting official rankings): built for launch, but if recon finds no such reporting this season, the adapter emits zero rows and the engine runs unconstrained — that is a valid state, not an error.

### 5.6 Renormalize + bootstrap (Readme §3.5–3.6, delta: interval level)
- Renormalize over the active set.
- **Bootstrap:** B=1000 replicates; resample observations with replacement ∝ w_k; recompute Steps 5.3–5.5 per replicate.
- **Report 89% intervals** (5.5th/94.5th percentiles) — owner decision overriding Readme §3.6's 95%, keeping the dashboard's existing McElreath-style convention everywhere. Also report point estimate `S_i` from full data.
- **P(A>B)** = fraction of replicates where `S_A^(b) > S_B^(b)`.

### 5.7 P(win) and all derived products (delta: explicit definition)
- **Share = P(win).** `P(win)_i = S_i` renormalized over non-Gambit housemates (Gambit housemates are excluded from the matrix entirely, §6 — so the renormalization is automatic). No softmax, no Dirichlet layer, no momentum tilt. The owner can verify every number by hand.
- **Rank probabilities from replicates:** P(#1), P(top-3), P(top-5) = fraction of the 1000 replicates in which housemate i ranks 1st / within top-3 / within top-5. Podium slot probabilities (winner/runner-up/2nd-runner-up) come from the same replicates. **No new sampling machinery.**
- **Momentum = Δ share WoW:** `S_i(week) − S_i(week−1)`, computed from the aggregated share series (seeded weeks make week-9 momentum computable). Recomputed after eviction renormalization.
- **Statistical ties / decision rules (Readme §4, unchanged):** P(A>B) > 0.90 clear lead; 0.60–0.90 leaning; < 0.60 too close to call. These drive the dashboard's statistical-tie markers (ties broken alphabetically for display only).
- **Eviction renormalization (Readme §3.7, unchanged):** evicted → removed from active_set, S=0, renormalize, before next week's aggregation. Mid-week DQ/walkout enters via `manual_notes.csv` as an eviction.

## 6. Gambit housemates (delta: excluded from matrix)

Gambit housemates (per `config/twist.json`, twist provisional) **never enter poll aggregation** — they don't appear in save polls by construction:
- They appear on the dashboard in a separate **"auto-finalists" strip** with photo + name + status, **no share and no win number**.
- This supersedes the old standings-product convention ("P(#1) ≡ 0 but runner-up/top-3/top-5 eligible"): the podium projection and chips rank **matrix housemates only**. Record any finale-week reconciliation need for P11.
- The persistent Gambit warning banner stays, now pointing at the auto-finalists strip.

## 7. Sources & adapters (launch set — all four live for Sep 26)

| Source | obs_type | Grade q | n | Access | Adapter status |
|---|---|---|---|---|---|
| bbnaijadaily TotalPoll widget (poll 43005) | full_share | A (1.0) | actual votes (capped 5000) | requests+BS4, server-rendered, state-aware (live/partial/empty/unreachable/closed) | **Exists** (`parse_totalpoll`); Saturday fetch is the week's only snapshot |
| Manual FB-group rows | full_share | **B (0.7)** | actual votes if shown | volunteer transcription into `docs/polls.json` | **Exists** (manual log) |
| ngnews247 YouTube RSS titles | top_N=2 constraint | C (0.5) | pseudo 50 | RSS title regex (gambit-proof) | **Exists** (scraper); new constraint-row conversion in matrix builder |
| Official bottom-N / top-N via news blogs | bottom_N / top_N | A (1.0) | pseudo 200 | requests+BS4, one isolated parser | **NEW — needs source recon this week**; zero-rows is a valid state |

- **Manual grades (decided):** transcribed bbnaijadaily result images = **grade A** (they are the widget's final numbers; transcription risk noted in provenance); FB-group rows = **grade B**.
- Rules inherited: never scrape login/CAPTCHA-gated sources; respect robots.txt; log URL+timestamp+raw values for every row; `collection_method` on every row; excluded sources (X/Twitter, Instagram, WhatsApp, Apify) documented as excluded, never silently skipped.
- Post-finale extensions (Readme §5 tiers, **not in launch set**): Reddit PRAW (B), Telegram Telethon (B), Nairaland (C), Google Forms (C), YouTube comments sentiment (D). Each = one isolated adapter returning schema rows; PRAW/Telethon need new account+app registration, deferred to P11 planning.

## 8. Operational cadence (delta: single Saturday fetch, no midweek probes)

- **One fetch per week:** the Saturday run window (current ~2 h slot, inside the live-voting period, before the 21:00 close). No recurring midweek probing — the Saturday snapshot is the week's only live row; simplest writer story accepted at the cost of mid-week data freshness.
- **One-time exception (cutover only):** the pre-Sep-26 midweek rehearsal (§11) fetches once to validate the live DOM; that satisfies the 2026-09-20 handoff's "midweek dry run" recommendation, after which probing stops.
- Recovery tooling stays: raw widget HTML archived every run; `python -m src.scrape_polls --week N --reparse <archived.html>` rebuilds the snapshot offline; `--backfill` archives result images. A closed-state archive honestly downgrades and never fabricates.
- Sunday 19:00 eviction show → results released as an **image** → human transcription into `docs/polls.json` (runbook §6 workflow, unchanged) → those transcribed finals enter the matrix as past-week `full_share` seed rows (grade A, `provenance=transcribed_seed`); recency decay (λ^Δt) naturally discounts them. Transcribed finals are legitimate past-week input — they are **not** outcome leakage (the leakage rule was about anchoring *current-week* predictions on *current-week* finals; past-week observations in a rolling window are the design).

## 9. Output & schema (delta: adapt in place)

`predictions.json` keeps its field names where they map; the schema gate (`products_schema.py`) and deploy workflow gate are updated in the same change:

| Existing field | New engine fills with |
|---|---|
| share/median values | Aggregated `S_i` point estimates |
| 89% CrI bands | Bootstrap 5.5th/94.5th percentiles |
| `p_rank_1` / `p_top3` / `p_top5` chips | Replicate fractions (§5.7) |
| Podium + slot probabilities | Replicate-based podium (winner/runner-up/2nd runner-up) |
| Pairwise P(A>B) panel | Replicate fractions (unchanged semantics) |
| `polls` block | Retained, richer provenance (per-source rows, `n_collapsed`, `carried` flags, constraint applications + softenings) |
| `priors` block | Replaced by `engine` block: `"poll_matrix"` + full parameter dump (`cap`, `λ`, `ε`, `window_weeks`, `B`, grades, pseudo-n) from `config/poll_engine.json` |
| `precision` (lite) | Dropped — bootstrap is cheap; no lite mode exists |
| R-hat/diagnostics | Dropped — replaced by data-sufficiency notes (rows in window, sources reporting, carried count) |

**Dashboard: keep shell, swap data** (layout/branding/watermark/credits stay):

| Panel | Becomes |
|---|---|
| Trajectory line chart | `S_i` weekly series + 89% bootstrap CI bands (same visual) |
| Winner hero | Top P(win) housemate |
| Podium strip | Replicate-based slot probabilities |
| Rank-probability chips | Replicate fractions |
| Statistical-tie markers | P(A>B) decision rules (§5.7) |
| Momentum strip | Δ share WoW arrows |
| At-risk / hazard panel | Eviction-risk list: bottom-N constraint flags + lowest-share ranking (no Cox hazard) |
| Headline-vs-trend disagreement banner | **Dropped** (no β trend exists) |
| **NEW** auto-finalists strip | Gambit housemates, photo+name, no numbers (§6) |
| Freshness chip, methodology note, disclaimer, tracker panel | Stay; methodology text rewritten to poll-engine description incl. the correlated-voters limitation (same commenters recur across blogs/polls; no $0 dedup key — never claim independent sampling) |

## 10. Legacy disposition (delta: retire in place)

MCMC/BMA code, `notebooks/bbnaija_mcmc.py`, its 90+ tests, `.mcmc_*` checkpoint dirs, and the alpha-shift anchor wiring stay **untouched in the repo**; only the run path changes. No archival moves, no deletions, no git churn 4 days before a certified run. P11 decides their final fate. Active test suite = new engine's fixture-based tests (no network) + retained non-MCMC tests (scrapers, schema, quarantine).

## 11. Build plan & cutover (4 days)

1. **Tue Sep 23 – Wed Sep 24:** `src/poll_matrix.py` + `src/aggregate.py` + `src/products.py`; `config/poll_engine.json`; schema-gate update; fixture-based tests (reuse `tests/fixtures/totalpoll_live.html`, `totalpoll_closed.html`, `ngnews_rss.xml`, `result_article.html`).
2. **By Wed Sep 24:** transcribe archived result images (wk 1–8 where legible) into `docs/polls.json` as seed rows — **seed the matrix** so week 9 has a real window (weeks 7–8 minimum, earlier weeks if transcribable; illegible numbers are left out, never guessed).
3. **Official bottom/top-N recon** (Wed–Thu): scan news blogs for official ranking reporting this season; wire the adapter if found; document zero-rows if not.
4. **Thu–Fri Sep 24–25: midweek rehearsal** — full dry run of the new engine on the probe fetch + seeded matrix; hand-review every output number against the raw matrix; fix parsers against archived HTML if the live DOM misfires.
5. **Sat Sep 26: certified first publish.** Run inside the window; review; push. **Rollback = restore last-good `predictions.json`** (the 2026-09-20 morning MCMC output stays untouched until the new engine's first certified run replaces it).
6. **Sat Oct 3:** second run, then **finale ≈ Oct 4**. Post-finale: P11 review with accumulated concordance evidence decides next season's spec (cap posture, anchor strength, extra adapters, Gambit podium reconciliation).

## 12. Decision log (owner, 2026-09-22 interview)

| # | Decision | Notes |
|---|---|---|
| 1 | Build Readme.txt's engine as the only model; MCMC retired entirely | Motivated by the polls-vs-model accuracy gap |
| 2 | Live this season — certified debut Sep 26 | 4 days out; rehearsal + rollback mitigate |
| 3 | New spec supersedes Readme.txt; Readme.txt = historical | This file |
| 4 | All four launch adapters (widget, FB manual, ngnews, official-N) | ngnews as top-2 constraint; official-N may be zero-rows |
| 5 | P(win) = share (renormalized, non-Gambit) | Maximally transparent; no softmax/Dirichlet/tilt |
| 6 | **89% intervals, overriding Readme §3.6's 95%** | Keeps dashboard convention; recorded as explicit delta |
| 7 | Current Saturday window; **no midweek probes going forward** | One-time cutover rehearsal is the only exception |
| 8 | Dashboard: keep shell, swap data | MCMC-only panels dropped; auto-finalist strip added |
| 9 | Schema: adapt in place | Gate updated in same change |
| 10 | Seed matrix by transcribing wk1–8 result images | Recency decay discounts old weeks naturally |
| 11 | Latest-wins dedupe per source-week | `n_collapsed` audit column |
| 12 | Soften-on-conflict constraints | Full apply when agreeing; halfway pull on conflict; every softening logged |
| 13 | Momentum = Δ share WoW | Matches Readme's example table |
| 14 | **No cross-season backtest — weekly concordance instead** | Overrides Readme §6; predicted-vs-actual eviction ordering scored weekly (score_week.py pattern) as P11 evidence |
| 15 | Gambit housemates excluded from matrix; auto-finalist strip | Supersedes "runner-up eligible" standings convention |
| 16 | Legacy MCMC retired in place, not moved/deleted | P11 decides final fate |
| 17 | Manual grades: transcribed images A, FB rows B | Transcription risk noted in provenance |
| 18 | Cutover via midweek rehearsal; rollback = last-good predictions.json | (Formal go/no-go checklist not chosen) |
| 19 | **cap = 5000 stands** despite ~600k real widget votes | Raising it is a P11 decision |
| 20 | Carry-forward for poll-uncovered actives, flagged `carried` | Never fabricated |
| 21 | ngnews = top_N=2 constraint rows (C, pseudo-n 50) | Supersedes "concordance-only" for this source; never shares |

## 13. Out of scope (this overhaul)

- Any paid service, X/Twitter, Instagram, WhatsApp automation (documented exclusions).
- Reddit/Telegram/Nairaland/Google-Forms/YouTube-comment adapters (post-finale).
- Cross-season backtesting and parameter tuning before the finale (§12 #14).
- Repo cleanup of MCMC code, `.mcmc_*` dirs, stray screenshots (P11).
- Dashboard visual redesign (shell kept; only data remapping + one new strip).

## 14. Risks & open items

- **Live-DOM risk:** `parse_totalpoll` has never run against the real live widget (validated on synthetic fixtures only). Mitigation: midweek rehearsal + archived-HTML `--reparse`. This is the single biggest Sep 26 risk.
- **Thin window:** week-9 aggregation rests on weeks 7–8 seed rows + the Saturday snapshot. If transcription stalls, CIs widen honestly — do not fabricate.
- **Official bottom/top-N may not exist** this season; adapter ships anyway and may emit zero rows.
- **Gambit twist is provisional** — if it activates late, the auto-finalist strip and matrix exclusion must activate with it (driven by `config/twist.json`).
- **Single-source dependence:** with cap=5000 and only ~1–2 full-share sources early on, bbnaijadaily dominates. Manual rows + constraints + concordance logging are the checks; revisit at P11.
- **Housekeeping flag:** `hugginf_token.txt` sits at repo root — verify it is gitignored and rotate if it ever entered history (pre-existing issue, not introduced by this spec).
- **UNKNOWN (not blocking):** whether official weekly bottom-N/top-N reporting exists this season; whether weeks 1–6 result images are legible enough to transcribe.
