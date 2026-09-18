# Session handoff — 2026-09-18 (week-8 DM bug fix + fan-poll tracking decision)

**Read this first.** Everything below is committed. This file supersedes
`docs/session-handoff-2026-09-17.md` for session-to-session context; `knowledge.md`
carries the same facts in condensed form.

## Where the project stands

P0–P8 complete, system live (see the 2026-09-17 handoff for URLs and the Saturday
ritual). This session was **bug-fix + policy**, not build-out:

| Surface | Status |
|---|---|
| `notebooks/bbnaija_mcmc.py` | **`dm_win_shares` remainder-bin bug FIXED** (details below) |
| `tests/test_model.py` | +2 regression tests; model suite **16/16 green** (13 fast + 3 heavy, incl. full synthetic end-to-end ~7 min) |
| `docs/polls.json` | NEW — fan-poll tracker, week-8 snapshot logged + scored |
| `docs/predictions.json` | **deliberately untouched** (single-writer rule) — the fix ships via the Sep 19 Saturday run |

## The week-8 bug — what happened and why (do not re-learn this)

**Symptom:** Yusuf (active, never Gambit after week 5, `gambit_flag == 0`) had
`win_prob_median = 0.0`, HDI `[0, 1.1e-16]`, all rank probs 0, pairwise 0 vs
everyone — while his own weekly history medians (~5%, correct) contradicted it.
Meanwhile every other active housemate's snapshot median was slightly inflated vs
their history. Fan polls (Yusuf 6.43% / ~40k save votes) confirmed he was alive.

**Root cause:** numpy's `multinomial` treats the **last PASSED pval as the
remainder bin**. `dm_win_shares` passed `p[:-1]` (11 of 12 active columns), so:
1. the second-to-last active column (Temi Nkem) absorbed the leftover mass, and
2. the true last active column — Yusuf, last in the master roster — was computed
   as `1 − total` ≈ exactly 0.0 in every one of the 10k draws.

**NOT the cause (verified, do not chase again):** the Gambit filter. It was
byte-for-byte correct; Yusuf is simply the last active column, and the
remainder-bin theft had nothing to do with Gambit semantics.

**Fix:** pass the FULL probability vector to `rng.multinomial`. numpy consumes the
final category internally, so `1 − total` reconstruction is gone. The old
drift-shave hack (`if head.sum() > 1.0: …`) existed only to protect the `p[:-1]`
form and was removed — verified with 2,000 adversarial draws (incl. ~1e-12 cells,
196/2000 normalized vectors drifting >1.0): zero ValueErrors.

**Regression tests added** (`tests/test_model.py`):
- `test_dm_shares_never_zero_out_a_non_gambit_column` — bug signature is the
  **strongest** column zeroed ~100% of draws. Note: weak columns DO earn genuine
  exact zeros from the DM multinomial (~1–3% of draws for tiny true shares) —
  that is legal Dirichlet-Multinomial behavior, not the bug. The first version of
  this test asserted all columns <1% zeros and failed for exactly that reason.
- `test_dm_shares_gambit_zero_survives_full_vector_fix` — Gambit-zeroed columns
  stay exactly 0.0; rows conserve.

**Expected effect on the Sep 19 run:** Yusuf small-but-nonzero (poll-anchored
intuition ≈ a few % win share, not 0); every other median sheds the stolen
inflation (~1 point off the leaders). Podium order may reshuffle in the tail.

## Fan-poll tracking — owner decision: TRACK ONLY (2026-09-18)

Owner asked why we model engagement (CPI) instead of vote counts. Settled facts,
recorded so this never re-opens without new evidence:

- **No official vote counts exist** mid-season; Africa Magic publishes only the
  eviction verdict. The X API (the one real vote-like signal) is dead to us ($0
  ceiling; free tier removed Feb 2026).
- **Unofficial polls are fan-war telemetry, not election data:** bbnaijadaily.com's
  widget allows **up to 100 repeat votes per person** (its own text); the ngnews247
  YouTube polls and FB voting groups are self-selected. They answer "vote to save
  THIS Sunday", a different question than P(final winner).
- **Policy:** polls are logged **by hand** in `docs/polls.json` alongside the
  Saturday run, scored weekly for concordance, **never scraped into the pipeline,
  never a CPI/model input, no PLAN.md amendment**.
- **Week-8 scoring:** hazard concordance **38/55 pairs = 0.691** (Cox relative
  hazard vs poll save-% order; 0.5 = coin flip). Poll top-3 [Keivo, Temi Nkem,
  Ricky] vs model P(#1) top-3 [Temi Nkem, Chimsom Chuka, Flora].
- **Where they agree:** poll #1 (Keivo 19.25%) == model's safest nominated
  (hazard 0.69); poll #11 (Chimsom Chuka 5.31%) == model's most at-risk (1.82).
  The save-vote question and the Cox panel are largely aligned.
- **Where they disagree (the known limitation):** the winner model. Keivo (model's
  lowest P(#1) = 0.018) and Ricky poll high; Chimsom Chuka (model's #2, 0.222)
  polls last. Diagnosis: **blog coverage ≠ vote intensity** — quiet fanbases
  (Keivo, Ricky) vote hard but generate little coverage; high-coverage housemates
  can attract drama-driven anti-votes. This is the documented CPI limitation
  (README + dashboard methodology note). Known, stated, not patched.

## What this session did NOT do (so nobody assumes it)

- `docs/predictions.json` NOT regenerated — single-writer rule; the Saturday run
  owns it. The published file still shows the pre-fix week-8 numbers.
- No changes to the Gambit filter, count formula, priors, or BMA — frozen math
  untouched.
- `docs/track_record.json` still has no auto-scoring (pre-existing left-open item).
- The user's poll screenshot and `notebooks/p5_probe_noncentered.json` (pre-existing
  probe artifact) were left untracked on purpose.

## Left open (priority order — unchanged items from 2026-09-17, plus one)

1. **Sep 19 run — post-fix verification (NEW, first thing on Saturday):** after the
   run, verify Yusuf `win_prob_median > 0`, spot-check that other medians dropped
   slightly, and eyeball the BMA weights (week-8 came out suspiciously flat
   ~⅓/⅓/⅓ — if they're flat again, investigate LOO ELPD before pushing).
2. Tracker auto-scoring (~20 min; unchanged from the 2026-09-17 handoff).
3. P9 rehearsal (~1 h, recommended before Sep 19; unchanged).
4. P11 closeout after Oct 4 (unchanged).

## Decision log additions (2026-09-18)

- Fan polls are **track-only telemetry** — never pipeline inputs. Re-open only with
  a new data source that has deduplication or honest one-person-one-vote mechanics.
- DM shares must always pass the **full** probability vector to `multinomial`;
  any future refactor that re-introduces `p[:-1]` fails the regression test.
- The engagement-vs-vote-intensity gap (Keivo/Ricky class of housemate) is accepted
  as a known limitation of the CPI proxy for this season; it goes into the P11
  post-season review as the first candidate feature for a next-season spec.
