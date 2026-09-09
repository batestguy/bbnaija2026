# Code conventions (P2.7 — deliberately minimal)

- **Python 3.11** in `bap3` (primary) / `causality-handbook` (fallback). No env-specific syntax beyond 3.10.
- **Style:** PEP8, type hints on public functions, docstrings on every module + public function (the notebook run record must be readable as documentation).
- **Logging:** `logging` module, one logger per module, INFO to console with timestamps; every renormalisation, quarantine, gate check, and prior value is logged (auditability rule).
- **Formatting:** no formatter enforced (solo project); keep lines ≤ 100 chars.
- **Tests:** `pytest`, fixture files under `tests/fixtures/`, **no network access in tests ever** (live scraping only in manual smoke tests).
- **Config reads:** all twist/gambit/roster/season facts come from `config/*.json` at runtime — never hardcoded in `src/` or notebooks.
- **Data writes:** only `run_weekly.py` (or a human) writes under `data/` — single-writer rule.
- **Git:** small commits per phase task; message style = imperative summary + short body; no force-push to main.
