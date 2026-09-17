# Session handoff — 2026-09-17 (dashboard build-out + full system go)

**Read this first.** Everything below is committed and pushed (`731c998` at time of
writing). A fresh session needs nothing from chat history — this file plus
`knowledge.md` are the source of truth.

## Where the project stands

**P0–P8 complete. The system is live and certified on real data.** Remaining work is
season operations (Saturday runs) plus two small optional items, listed at the end.

| Surface | URL | Status |
|---|---|---|
| GitHub Pages (primary) | https://batestguy.github.io/bbnaija2026/ | live, real week-8 posterior |
| HF Static Space mirror | https://batestguy-bbnaija2026-dashboard.static.hf.space/ | live |
| HF Dataset archive | https://huggingface.co/datasets/batestguy/bbnaija2026-predictions | live |
| GitHub repo | https://github.com/batestguy/bbnaija2026 | `main`, deploy workflow green |

- **Model validated at production settings:** 3 candidates × 4 chains × 2000 draws,
  **0 divergences, R-hat max 1.0028** (`notebooks/p5_full_validation.json`), and the
  first real-data run reproduced it (`data/predictions.json`, week 8).
- **Week-8 headline:** Temi Nkem 0.341 / Chimsom Chuka 0.171 / Tram 0.117.
  Top-4 are within statistical noise of each other (overlapping 89% HDIs).
- **Tests:** 49/49 green (fast suite `pytest -m "not e2e"` in ~30 s; e2e right-sized to
  ~8 min, exercised separately).
- **README rewritten** with the full mathematical specification, pipeline diagrams,
  screenshots, and ops instructions.

## What this session built (all pushed)

1. **P5 geometry fix closed out** (`1c01585`, earlier): finite-only R-hat max (the LKJ
   diagonal poisoned the old max with NaN) + non-centred offsets + sum-to-zero centring +
   `target_accept=0.95`. The `s_beta` orphan is wired — BMA candidates genuinely differ.
2. **P6 runner** (`38b80d3`): `run_weekly.py` — full-history CPI rebuild every run (never
   week-sliced), UTF-8 subprocess logs (Windows cp1252 noise killed), full spec default
   tier, console review, auto-copy to `docs/`.
3. **P8 deploy** (`85c3276`): push-trigger-only workflow — schema gate first, then Pages +
   HF sync (`create_repo(exist_ok=True)` bootstrap; `HF_TOKEN` secret is set).
4. **Dashboard build-out** (`7e8a8e3` → `731c998`): winner hero, freshness chip,
   OG/WhatsApp share cards + `social-card.png`, share button, methodology accordion,
   500px chart with hover tooltip + line focus (static annotations removed),
   race-to-the-finale momentum strip (replaces the old trend podium), red
   disagreement banner when trend ≠ headline (βᵢ/σ_week rendered as Greek),
   bolder watermark, JJMB builders credit, prediction-vs-outcome tracker panel
   (hidden until first scored week), mobile pass verified at 375px.
5. **On-canvas name labels removed** per owner feedback — identity lives in the legend
   (color + photo).

## Lessons recorded this session (do not re-learn these)

- **Hibernation survives, hard power-cut costs one candidate.** The Sep 16 outage left
  the nohup'd run intact. Checkpointing + `--resume` covers the hard-kill case; never
  sample without it.
- **Trust the owner's eyes over green programmatic checks.** Two race-strip bugs shipped
  past clean console logs: an invalid `style=…;class=…` string-surgery that stripped the
  avatar class (giant photo overlay), and `left:0.86%` vs `86%` (runners bunched at the
  left edge). Both classes of bug are visible in a screenshot and invisible in
  `innerHTML` — screenshot-verify anything visual before pushing.
- **`upload_folder/upload_file` need the repo to exist** on HF — `create_repo(exist_ok=True)`
  first; `space_sdk` belongs to `create_repo`, not `upload_folder`.
- **Windows console cp1252** chokes on `→` in subprocess logs: force UTF-8 env in the
  runner (already done — don't regress it).
- **ArviZ rhat over structural constants → NaN** poisons a max over all coordinates;
  any new gate must filter non-finite before taking maxima.

## The Saturday ritual (P10.1) — ~2.5 h machine time, ~10 min human

```bash
git pull
BBN_MCMC_CORES=4 python run_weekly.py     # scrape → CPI → 3×(4×2000) → BMA → gates → review
# read the WEEKLY RUN REVIEW block; verify gates all PASS
git add docs/predictions.json && git commit -m "week N run" && git push   # deploys everywhere
```

- Run dates left this season: **Sep 19, Sep 26, Oct 3** (finale Sun Oct 4).
- `--lite` exists but is honestly labelled; prefer full unless the clock forces it.
- A crash/sleep mid-run only costs the in-flight candidate (`--resume` reloads
  `.mcmc_checkpoints/`).
- Evictions/DQs/walkouts go through `data/raw/manual_notes.csv`, never hand-edited
  status. Then re-run preprocess (the runner does the full history anyway).
- If a gate fails: keep the last published file live (it is), read the gate diagnostics
  naming the worst coordinates, do not tune silently — record any change in a commit.

## Left open (in priority order)

1. **Tracker auto-scoring (~20 min).** `docs/track_record.json` + the dashboard panel
   exist; nothing appends rows yet. Wire into `run_weekly.py`: after Sunday's eviction is
   known (entered via `manual_notes.csv` the next morning), append
   `{week, predicted_winner, predicted_prob, evicted, hit, brier}` from last week's
   archived products + the week's eviction probabilities.
2. **P9 rehearsal (~1 h, recommended before Sep 19):** full dry run of the Saturday
   ritual on live data, including a deliberate `--resume` from a killed candidate.
3. **Runner default `target_accept`:** the runner exports `BBN_TARGET_ACCEPT=0.95`
   (validated value). If you change it, re-run the 4×2000 validation before Saturday —
   never ship an unvalidated geometry dial.
4. **Season closeout (P11, after Oct 4):** final standings freeze, archive the dataset
   repo with a tag, write the post-season accuracy review (tracker is the input).

## Decision log (do not re-open without new evidence)

- Stack pinned: PyMC 5.8 + ArviZ on `bap3`. R/brms/Stan/Quarto rejected (geometry
  problem is language-independent; brms can't express the joint ZINB+Cox likelihood).
- Zero-divergence required on the headline candidate; residue on non-headline
  candidates tolerated only with weights 0 via the gate. In practice: all three clean.
- Trend readout is a momentum-only what-if and must stay secondary; the red
  disagreement banner (added this session) is the contract with readers.
- Placeholder output is never publishable as predictions.
- Single-writer rule: the only writers are `run_weekly.py` + a human push. No cron.
- $0 ceiling: no paid services; the only secret is `HF_TOKEN` (fine-grained
  `bbnaija-deploy`, rotate via HF settings → GitHub secret update if ever needed).
