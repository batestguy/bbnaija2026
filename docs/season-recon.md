# Season Reconnaissance — BBNaija Season 11 "Show Ya Sef" (P1)

> Researched 2026-09-09 (Wednesday, mid-season). All claims sourced; confidence tagged per item.
> **Bottom line: the season is LIVE and mid-flight.** Premiere was 26 Jul 2026; today is week 7 of ~10. The project enters at P10-equivalent urgency: the first Saturday run must backfill weeks 1–6 from archives before any live prediction publishes.

## 1. Season timeline (VERIFIED — Wikipedia, DStv, Punch, Premium Times)

| Item | Value | Source |
|---|---|---|
| Season | 11 — "Show Ya Sef" | Wikipedia |
| Premiere | Sunday **26 July 2026**, 7pm WAT (DStv 198 / GOtv 29) | Punch, Premium Times |
| Length | **72 days** → finale ≈ **Sunday 4 October 2026** (TO CONFIRM officially) | Wikipedia infobox |
| Housemates | **24** at launch | Wikipedia, Vanguard, Punch |
| Grand prize | ₦160 million (cash + sponsor prizes) | Vanguard, Guardian |
| Host | Ebuka Obi-Uchendu (10th consecutive season) | Wikipedia |
| Auditions | 16–20 May 2026, Lagos/Enugu/Abuja | P.M. News |

Week calendar (premiere-anchored): W1 = Jul 26–Aug 1 · W2 = Aug 2–8 · W3 = Aug 9–15 · W4 = Aug 16–22 · W5 = Aug 23–29 · W6 = Aug 30–Sep 5 · **W7 = Sep 6–12 (current)** · W8 = Sep 13–19 · W9 = Sep 20–26 · W10 = Sep 27–Oct 3 · Finale Sun Oct 4.

**The next Saturday run is Sep 12 (week 7's close); the first backfill target is weeks 1–6.**

## 2. The Gambit twist (CONFIRMED — no longer provisional)

- **Week 1 rule (verified, DStv 29 Jul + Wikipedia Note 1):** the male and female housemates with the most week-1 public votes become **The Gambit**: regular housemates, compete in all tasks, **automatic finale slot**, but **ineligible to win the grand prize**. The frozen eligibility-filter math applies exactly.
- **Week 1 result (verified, vote shares):** **Flora (29.18%)** and **Aikou (9.10%)** became The Gambit. (Ricky 7.18%, Abi 6.87% were next.)
- **"Operation Release the Gambit" (verified, Punch 31 Aug + Vanguard 30 Aug):** announced on the week-5 Sunday live show (Aug 30); viewer vote decided whether to release one or both. **Result: both Aikou and Flora exited Gambit mode and are now eligible to compete for the ₦160m.** (Instagram/threads fan posts corroborate.)
- **Modeling consequence:** `GambitFlag_i` is **weekly-varying**, not season-static:
  - `gambit_flag_i,t = 1` for Aikou & Flora during **weeks 1–5** (they still hold finale slots from week 1 → they must appear in standings as "finale-locked, prize-ineligible" in that window),
  - `gambit_flag_i,t = 0` from **week 6 onward** (both prize-eligible).
  - `config/twist.json` therefore needs **per-housemate week ranges**, not a single static list: e.g. `gambit_periods: [{"name": "Flora", "weeks": [1,2,3,4,5]}, {"name": "Aikou", "weeks": [1,2,3,4,5]}]`.
  - Historical-week standings (backfilled) must apply the filter to those weeks; current-week standings apply none (nobody is currently Gambit-flagged).
- **Dashboard:** the Gambit banner logic becomes historical — during backfilled weeks 1–5 the banner names Flora/Aikou; from week 6 it hides (no active Gambit) unless a new Gambit-style twist is announced. The twist.json schema change must be reflected in `specification.md`.

## 3. Housemate roster (24 — VERIFIED, Punch full list + Wikipedia table)

Canonical name = show/brand name (voting name); aliases catch press variants. Status per Wikipedia exit table (day numbers from premiere).

| # | Canonical | Full name | Sex | Status |
|---|---|---|---|---|
| 1 | Tram | Joshua Alekewumu | M | active |
| 2 | Abi | Abisola Ayoola | F | active |
| 3 | Aikou | Amyr Yousufzai | M | active (Gambit w1–5) |
| 4 | Araga | Oluwaseyifunmi Sosanya | M | active |
| 5 | Barry | Muudumbari Pop-Yornwin | M | active |
| 6 | Bells | Isabella Imoh | F | active |
| 7 | Bluethopia | Usaku Bantai | F | active (spellings seen: Bluethopia/Bluethophia — alias both) |
| 8 | Cassi | Ezenwoke Nwosu | M | **evicted wk 4 (Aug 23, 5.27% votes — BellaNaija/Premium Times)** |
| 9 | Chimsom Chuka | Chimsom Chuka-Okoli | M | active (alias "Chimsom") |
| 10 | Flora | Flora Egbedi | F | active (Gambit w1–5, released) |
| 11 | Gerard | Gerard Adebaji | M | **evicted wk 6 (Sep 6)** |
| 12 | Goddessa | Lovette Okechukwu | F | **evicted wk 5 (Aug 30 double — bbnaijatoday tracker)** |
| 13 | Keivo | Victor Ikpe | M | active |
| 14 | Kamsy | Kamsy Uzoma | F | **evicted wk 3 (day 21, Aug 16 — Channels TV)** |
| 15 | Mercedes | Ijeoma Emi | F | **evicted wk 2 (day 14)** |
| 16 | Martins | Martins Iyeh | M | **evicted wk 2 (day 14)** |
| 17 | Neche | Chinecherem Maduagwu | F | **walked (day 21)** — `status: walked` proposed; log in `manual_notes.csv` |
| 18 | Nomy | Whitney Chukwu | F | active |
| 19 | Oyin | Oyindamola Oshikoya | F | active |
| 20 | Ricky | Patrick Jumbo | M | active |
| 21 | Sheba | Faith Gamde | F | active |
| 22 | Sultex | Sultan Aregbe Obanikoro | M | **evicted wk 5 (Aug 30 double)** |
| 23 | Temi Nkem | Temitope Chigbue | F | active |
| 24 | Yusuf | Yusuf Muhammed-Awal | M | active |

**Active today: 16.** Complete exit ledger (8 exits, fully reconciled with "Gerard = 8th exit" per BellaNaija):

| Week | Date | Exits |
|---|---|---|
| W2 | Aug 9 (day 14) | Mercedes, Martins (evicted) |
| W3 | Aug 16 (day 21) | Kamsy (evicted), Neche (walked) |
| W4 | Aug 23 (day ~28) | Cassi (evicted, 5.27% votes) |
| W5 | Aug 30 (day ~35) | Sultex, Goddessa (evicted, double) |
| W6 | Sep 6 (day ~41) | Gerard (evicted) |

Note: "4th housemate evicted" (Arise TV, Cassi) vs "5th to leave" (BellaNaija, Cassi) reconciles exactly by whether Neche's walk is counted as an exit. The earlier Wikipedia-table gap (Cassi/Sultex/Goddessa rows showing `Ineligible`) = they had exited, hence ineligible.

**Aliases/notes for `config/housemates.json`:** Gerard/「Gerald」(Punch profile spells "Gerald", Wikipedia "Gerard" — canonical **Gerard**, alias Gerald) · Bluethopia/Bluethophia · Chimsom Chuka/Chimsom · Temi Nkem/TemiNkem · press may use full names (e.g. "Yousufzai", "Obanikoro") — alias map must include surnames.

## 4. In-house mechanics observed (feeds AtRisk coding)

- **Head of House** exists (W1: Chimsom Chuka; W2: Sheba; W3: Neche; W4: Abi per Wikipedia nominations table) — HoH immunity weeks affect who is AtRisk. Nomination data is published weekly in the Wikipedia table + blog recaps → `AtRisk` can be coded from **nominated lists**, cross-checked against blog posts (spec D1's "not everyone is up every week" is confirmed: e.g. week 6 had **15 nominated**).
- Week-2 had a team/immunity structure (Note 2); HoH-team immunity variations are a data-coding concern for `AtRisk`, not the model.
- Nominations became "Ineligible" for some housemates in later weeks (columns show `Ineligible` for w4–w7 rows) — likely twist-related (possibly Gambit-related immunity). TO VERIFY semantics when coding weekly AtRisk.

## 5. Source health (P1.4)

| Source | Verdict | Notes |
|---|---|---|
| Google News RSS | **PRIMARY — healthy** | Per-housemate query `"HousemateName" OR "BBNaija"`; results all season long (this recon itself ran through it). Stable schema. |
| Wikipedia S11 article | **HIGH-VALUE SECONDARY** | Nominations/voting/eviction tables + footnoted rules = best structured AtRisk/exit ground truth. Treat as a **structured source with a dedicated parser candidate** (P3 scope addition worth considering; tables are stable). |
| BellaNaija | **Healthy** | Weekly eviction recaps with dates (Gerard wk6 confirmed here); tagging pages scrapeable. |
| Punch | **Healthy** | Full roster with profiles; twist coverage (Release-the-Gambit). Standard article pages. |
| Vanguard | **Healthy** | Confirms eviction counts + twist coverage. |
| DStv / Africa Magic | **Healthy but JS-heavy** | News articles parse fine (Gambit intro article); housemates page is app-like — prefer RSS/news pages over the SPA pages. |
| Channels TV | Healthy | Eviction confirmations. |
| Pulse Nigeria | Not directly sampled in this recon — include in P3 smoke test as planned. | |
| Legit.ng | Healthy | Roundup coverage (wk6: "Barry wins Most Influential Player"). Usable as supplementary mention counting. |

## 6. Decisions this recon forces (fold into P2–P5)

1. **`config/season.json` is now real, not placeholder:** `premiere_date: 2026-07-26`, `finale_date: 2026-10-04` (confirm), `eviction_day: sunday`, `season: 11`, `label: "Show Ya Sef"`.
2. **`config/twist.json` schema upgrade:** per-housemate Gambit **week ranges** (verified above) instead of a static list. Filter math unchanged; config feeds it.
3. **Backfill-first plan:** weeks 1–6 must be reconstructed from archives (RSS is queryable retroactively; Wikipedia tables give exact nomination/eviction ground truth per week; BellaNaija recaps per week). The first live run is a **backfill run** — expect it to be slower and reviewed extra carefully.
4. **Neche's walk needs a `status` decision** (propose `walked`, or `evicted` + note) — small spec amendment, user-visible in the dashboard badge.
5. **Week-4/5 evictee names TO VERIFY** before roster statuses are final (double-eviction weeks implied).
6. **Wikipedia as a structured secondary source** (nominations, exits, vote shares) — recommend a dedicated parser in P3; it materially de-risks AtRisk coding.

## 7. Confidence summary

- Season dates, roster, Gambit mechanics + release: **VERIFIED** (multiple independent outlets).
- Full exit ledger weeks 2–6: **VERIFIED and reconciled** (8 exits; wk4 = Cassi, wk5 = Sultex + Goddessa double).
- Finale date: **high confidence** (72-day infobox) but TO CONFIRM against an official announcement.
- Pulse scrapeability: **UNSAMPLED** (P3 smoke test).
