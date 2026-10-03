# Session handoff — 2026-10-03 (finale-week run; Keivo DQ reconciled; methodology equations corrected; demo video rebuilt 90s → 2m39s)

**Read this first.** This file **supersedes `docs/session-handoff-2026-09-27.md`**
(kept as history). Operational doc for Saturdays: **`docs/engine-runbook.md`**.
Spec: `poll-matrix-engine-spec.md`. Phases: `PHASES.md` E-campaign.

Commits this session: `2347bdd` (engine scoring/config fixes) · `ec8c75c`
(finale week 10 + Keivo DQ reconcile) · `c08f749` (methodology section + PDF) ·
`c87206b` (carry-over validation design) · `3405c52` (dashboard week control) ·
`fb17062` (poll-log prose) · `0f7bb92` (first demo video) · `195e74f`
(**equations corrected**) · `0ec5e13` (**video rebuilt**).

**Not pushed.** Everything above is local; `git status` is clean.

## What happened this session (in order)

1. **Finale-week run (E6.3) + Keivo DQ reconcile.** Week 10 published
   (`data/predictions.json`, generated 2026-10-03 08:48, precision full,
   `docs/` mirrors synced). Podium **Sheba 0.945 / Temi Nkem 0.926 / Ricky
   0.917**. Keivo's 2026-09-30 disqualification is coded as the week-10 exit in
   `data/raw/manual_notes.csv` and surfaced as a status badge, not an eviction.
2. **First scored week in the track record.** `src/score_week.py` appended
   week 10 to `docs/track_record.json`: predicted winner Sheba **survived**
   (hit), Brier **0.0432**, poll concordance **0.50**, top-hazard pick Aikou
   missed (the DQ was not the model's at-risk pick — an honest miss, kept).
   Weeks 3/7/8 carry `scored:false` tombstones: no snapshot predates them.
3. **Engine + doc corrections** (`2347bdd`, `fb17062`): poll-matrix scoring and
   stale config/docs fixed; the MCMC-era `precision` field dropped; retired
   poll-anchor prose corrected in the poll log. **134 tests pass in ~7 s.**
4. **Methodology section on the site** (`c08f749`): dependency-free HTML/CSS
   equations (no MathJax/KaTeX/CDN — the zero-dependency posture holds), a print
   stylesheet that emits only that section, and `docs/assets/methodology.pdf`
   generated from the same `index.html` so there is no second copy to drift.
5. **Dashboard week control** (`3405c52`): the trajectory x-axis can step back
   through the window (wk 9 / wk 10); every line, marker and tooltip re-scopes.
6. **The equations were wrong — in two places.** (a) The README's aggregate was
   written as a weighted mean of **raw** row shares; the engine renormalises
   each row over the set it covers first (`_row_shares_over`), so a nominated
   poll covering three housemates was documented as if it could read as a
   landslide. Split into the two steps it actually is, and the equations that
   existed only as prose (window, carry-forward, both constraint bounds, the
   halfway pull, renormalisation, interval percentiles, P(#1)/P(A>B), momentum)
   are now written down — plus a new **Step 7** for the scoring maths, which had
   none. All 35 expressions KaTeX-validated: `\text{89% interval}` needed an
   escaped percent (it was silently eating the rest of the line as a LaTeX
   comment), and GFM-unsafe `\{` / `\operatorname` were replaced. Test count
   corrected 138 → **134**, and the `pytest -m "not e2e"` split was dropped —
   **no `e2e` marker exists in the suite**, so both documented invocations ran
   the same 134 tests.
7. **Demo video rebuilt: 90 s → 2m39s, 7 cards → 14.** The published video's
   maths was wrong twice over: `λ^Δt_k` drew the exponent and subscript as
   sibling runs (the `k` landed *beside* the exponent), and the aggregate was an
   inline slash rather than a stacked fraction. `make_cards.py` now has a small
   box-layout engine (`Sym`, `Row`, `Script`, `Frac`, `BigOp`, `Tilde`) so
   scripts nest and fractions stack. The method is now the subject: window →
   weights → per-row renormalisation → aggregate → carry-forward → constraint
   bounds + soften-on-conflict → two-layer bootstrap → interval / P(#1) /
   P(A>B) → `share = P(win)` → weekly scoring, then the live dashboard. The
   close card carries the real track record (it previously had blank badges).

## Current state

| Thing | State |
|---|---|
| Engine | poll_matrix, 2-row window (wk9 seed + wk10 final), 6-source registry, seed 20260922 |
| Products | `data/predictions.json` wk10, precision full, `docs/` mirror synced; data-review.html regenerated |
| Dashboard | Live at batestguy.github.io/bbnaija2026 (as of `0f7bb92`, **not** re-verified live this session) |
| Track record | 1 week scored (wk10): winner hit, Brier 0.0432, concordance 0.50 |
| Video | `docs/assets/bbnaija2026-demo.mp4` — 2m39s, 8.8 MB, captions burned in + `.srt` |
| Tests | 134 passed, ~7 s, offline |
| Deploy | **not pushed** — the live site still serves the pre-session build |

## Next session (or owner actions) priority order

1. **Sun Oct 4 = FINALE (E6.4).** Grade the podium via `src/score_week.py`:
   transcribe the finale result image into `docs/polls.json`, log the exit(s)
   in `data/raw/manual_notes.csv`, run the scorer. The engine's first true
   champion test — Sheba was called at 95%.
2. **Push + verify the deploy.** Two commits are unpushed; the live site
   currently shows the old README-linked 90-second video. Bump nothing in
   `docs/assets/script.js` (unchanged this session) — `?v=` only matters for
   script edits.
3. **E6.5 / P11 closeout**: cap posture, anchor strength, Gambit podium
   reconciliation, legacy MCMC dir removal decision.
4. **E5.2 recon verdict** still owed in `docs/season-recon.md`; owner
   transcription of the wk6/wk7 images still open.

## Gotchas worth remembering (new this session)

- **The demo build pipeline is unversioned.** `output/` is gitignored, so
  `make_cards.py`, `build_demo.py`, `capture_demo.cjs`, the card generator's
  fonts and every capture live outside the repo — the video cannot be rebuilt
  from a fresh clone. Worth promoting the three scripts to a tracked `tools/`
  (fonts left as a documented drop-in). **Open item, not done.**
- **Card space is a hard constraint**: burned-in captions own everything below
  `FOOT_Y = H-215`. `save()` now fails the build if a card's content reaches
  it, so copy edits must be paid for by dropping the formula size.
- **Two build guards in `make_cards.py`**, both deliberate: glyph coverage
  (catches the Σ/Δ/λ empty-box class of bug) and the caption-band overflow.
- **Caption alignment is checked, not trusted** (`check_timeline`): the first
  rebuild put the renormalisation narration on top of the aggregate card
  because the cue times were written against an earlier segment plan.
- **Caption figures must be read from `predictions.json`**, not from an earlier
  run's notes — the video said 94% P(#1) where the published file says 0.945.
- The card close-up: **podium slot probability ≠ P(top-3)** (0.945 vs 0.945 here
  for Sheba, but Ricky is 0.917 slot vs 0.99 top-3). Different, both-correct
  quantities — don't equate them in an audit.
