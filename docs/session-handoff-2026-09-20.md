# Session handoff — 2026-09-20 (poll-anchored prior + multi-source poll scrape)

**Read this first.** Everything below is implemented and tested. This file supersedes
`docs/session-handoff-2026-09-18.md` for session-to-session context; `knowledge.md`
carries the same facts condensed. **Operational doc for Saturdays:
`docs/polls-runbook.md` — read it before the Sep 26 run.**

## Where the project stands

P0–P8 complete, system live. This session was **policy reversal + build**, triggered
by the owner's question: *"How is Chisom winning, isn't Nkem's engagement higher?"*
and its follow-up *"We have to include the online polls into our calculations."*

| Surface | Status |
|---|---|
| `src/scrape_polls.py` | **NEW** — multi-source poll scraper (bbnaijadaily / ngnews247 / manual) + median-of-sources anchor builder + `--backfill` + `--reparse` recovery |
| `notebooks/bbnaija_mcmc.py` | poll-anchored prior wired in (`load_poll_anchor`, `poll_shift_vector`, `build_model(poll_shift=…)`); count formula **byte-for-byte untouched** |
| `run_weekly.py` | new best-effort `polls` stage between preprocess and model; review prints anchor status |
| `src/products_schema.py` | optional `polls` block validation (structure hard, values checked) |
| `tests/test_scrape_polls.py` | **NEW** — 22 fixture-based tests; full suite **93 passed** (91 at implementation time + 2 reparse tests) |
| `docs/polls.json` | method string rewritten for the new policy (2026-09-18 track-only row preserved as history) |
| `AGENTS.md`, `knowledge.md`, `README.md` | amended (architecture list, modeling rule, decision log, methodology + test counts) |
| `docs/predictions.json` | **deliberately untouched** — the 2026-09-20 morning run's output is the last-good file; the anchor first bites in the **Sep 26 run** |

## The investigation that started this (settled facts — do not re-derive)

Why Chimsom Chuka P(#1)=0.365 vs Temi Nkem 0.040 despite the owner's perception that
Nkem's engagement is higher:

1. **CPI is effectively "article mentions" only.** `comments`/`shares` are `null`
   for every housemate every week (`scrape_blogs.py` hardcodes them `None`; no
   source exposes counts), so the 0.4/0.3 weight mass renormalises onto
   mentions+headlines. And `headline_features == article_mentions` in every record
   (perfectly collinear), so CPI ≈ min-max normalized weekly article mentions.
2. **Chimsom dominates blog coverage**: mentions 48/19/19/23/30/20/15/38 (wk1–8),
   CPI at the weekly max 5 of 8 weeks. **Nkem's coverage collapsed** in wk7–8:
   1 and 4 mentions → CPI 0.0 twice.
3. The polls (the signal the owner trusts) had Nkem #2 (17.02%) and Chimsom dead
   last (5.31%) in the logged wk-8 snapshot. The model never saw any of it —
   polls were **track-only** by the 2026-09-18 decision. Hence the perceived
   injustice: the model measures press coverage, the owner was watching fan votes.
4. Pre-bug-fix, the wk-8 model even had Nkem at P(#1)=0.341; the Sep-20 run has her
   at 0.040 — the coverage collapse is what moved her, not a poll change.

## The decision (owner, 2026-09-20 — supersedes 2026-09-18 track-only)

Chosen via structured options: **(a) Poll-anchored prior** over 4th-BMA-candidate /
CPI-term / post-hoc blend, and **(b) automated widget scraping** over manual-only
pasting. The re-open condition from 2026-09-18 ("dedup or one-person-one-vote
mechanics") was NOT met — the owner consciously accepted the repeat-vote caveat
(bbnaijadaily allows up to 100 votes/person). The mitigation is that the anchor is
deliberately **weak** (below) and CPI stays the dominant driver.

## Source reconnaissance (verified 2026-09-20, do not re-scrape to re-learn)

- **bbnaijadaily**: TotalPoll **v4.7.0** (WordPress), poll id **43005**, container
  `#totalpoll-poll-43005`. **Server-rendered** (closed-state message visible in raw
  HTML — requests+BS4 suffice, no headless browser). Voting opens Mon 20:00, closes
  **Sat 21:00**; afterwards: `"Voting is Closed (since N hours). Result are being
  collated by Deloitte"` and the widget renders no choices. Past-week "Vote Result"
  articles publish the final chart **as an image** (WhatsApp screenshot — verified
  week 7; zero percentages in article HTML).
- **ngnews247**: poll results exist as **YouTube video titles**
  (`BBNAIJA 2026 WEEK 8 VOTE POLL RESULT: KEIVO & RICKY | …`), rank-only. Two
  different wk-8 leader pairs were observed (RICKY & TEMI NKEM ~Sep 14, then
  KEIVO & RICKY ~Sep 18) — mid-week snapshot shifts are real. GAMBIT poll videos
  have no week number and can never be confused with save polls by the title regex.
- **FB voting groups**: login-walled — manual log only, forever.

## Implementation (the guarantees that matter)

- **Anchor math:** `m_i = 0.25 · clip( log( s_i · n ), ±log 4 )`, `s_i` = **median**
  normalized share across full-share sources (bbnaijadaily live + manual rows),
  `n` = anchored housemate count. Location shift on the alpha column, pre-centering;
  scale, LKJ correlation, BMA structure, and the count formula unchanged.
- **Gap tolerance as an invariant:** all-zero shift ≡ un-anchored spec — missing
  snapshot, dark/closed widget, uniform poll, unreachable site all degrade to the
  exact pre-poll model. `snapshot_type` gates it: only `"midweek"` anchors;
  `"final"` (backfill/reparse-of-closed) never does (outcome-leakage rule).
- **Single-writer intact:** the poll stage runs inside `run_weekly.py` and is
  best-effort (`try/except` like `score_previous`) — a poll failure logs and
  continues un-anchored; it can never reject the certified run.
- **Recovery:** raw widget HTML is archived every run;
  `python -m src.scrape_polls --week N --reparse data/raw/week_XX/polls_bbnaijadaily.html`
  rebuilds the snapshot offline after a parser fix. A closed-state archive honestly
  downgrades to `final` and never anchors.
- **Auditability:** anchor constants + per-housemate shifts recorded in the snapshot,
  `predictions.json → polls` + `priors.poll_anchor`, and the run-review console line.

## What this session did NOT do (so nobody assumes it)

- **No re-run of today's predictions** — the owner chose the scrape channel, not a
  same-day re-run. `docs/predictions.json` still holds the 2026-09-20 morning run.
- **No week-8 finals logged yet** — results are embargoed until the Sunday 19:00
  show. Transcribe after (runbook §6).
- **The live-DOM parser is validated only against a synthetic fixture.** The real
  live widget could not be captured on 2026-09-20 (voting was closed). First real
  validation is the Sep 26 live window (or a mid-week dry run). Archived raw HTML +
  `--reparse` make any drift recoverable.
- No changes to the Gambit filter, count formula, priors families, or BMA — frozen
  math untouched except the documented alpha-column location shift.
- No git commit made in this session (owner commits/pushes per the Saturday ritual).

## Left open (priority order)

1. **Sep 26 run — first anchored run:** after the run, verify the runbook §4
   checklist (state=live, no unexpected quarantines, `Poll anchor : APPLIED`,
   plausible podium). If the parser misfires mid-window: fix `parse_totalpoll`
   against the archived HTML → `--reparse` → rerun the model stage.
2. **Mid-week dry run (recommended):** Tue–Fri, run the poll stage standalone
   (`python -m src.scrape_polls --week 9` — writes snapshot files only, no model)
   to validate the live DOM before it matters. Delete the probe snapshot
   afterwards, or leave it — the Saturday stage overwrites it.
3. **Wk-8 finals → `docs/polls.json`** after tonight's show (transcription, §6),
   then `python src/score_week.py` to score wk-8 concordance.
4. **Temi Nkem wk-8 raw undercount check:** raw RSS grep found 8 week-8 items
   mentioning nkem/temitope but preprocess counted 4 article mentions. Alias config
   looks correct; the discrepancy (dedupe? item vs article semantics?) was never
   closed. One-hour audit, worth doing before trusting wk7–8 CPI fully.
5. Carried forward from 2026-09-18: tracker auto-scoring (~20 min); P9 rehearsal;
   P11 closeout after Oct 4 — the coverage-vs-vote-intensity gap (Keivo/Ricky/Nkem
   class) is now *weakly anchored against*, and P11 remains the venue for deciding
   whether next season's spec should anchor harder.

## Decision log additions (2026-09-20)

- Poll-anchored prior replaces track-only. Re-open again only with an honest
  one-person-one-vote source, or via P11 with season evidence.
- Backfilled FINAL poll data must never enter the likelihood (outcome-leakage rule);
  concordance scoring and post-season review are its only consumers.
- The poll stage is best-effort by contract: it may degrade the run to un-anchored,
  it may never block or reject the certified run.
- `snapshot_type` (`midweek`/`final`) is the enforcement mechanism — any future
  refactor that lets the model read `final` snapshots fails the design review.
