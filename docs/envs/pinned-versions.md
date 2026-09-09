# Pinned modeling environments (P2.6)

Captured 2026-09-09 via `conda list`. Working copy + `data/` live on **D:**; envs on **C:**.

## Primary: `bap3`

`conda activate bap3`

| Package | Version |
|---|---|
| python | 3.11.6 |
| pymc | 5.8.0 |
| arviz | 0.16.1 |
| numpy | 1.24.4 |
| pandas | 2.1.2 |
| pytensor | 2.15.0 |
| nutpie | 0.9.1 |
| scipy | 1.11.3 |

## Fallback: `causality-handbook`

`conda activate causality-handbook`

| Package | Version |
|---|---|
| python | 3.11.14 |
| pymc | 5.25.1 |
| arviz | 0.23.4 |
| numpy | 1.26.4 |
| pandas | 2.3.3 |
| pytensor | 2.31.7 |
| scipy | 1.15.2 |

## Notes

- `bap3` is primary (matches PLAN.md); its older numpy 1.24 / pymc 5.8 are known-good for the ZINB + Cox joint model.
- If a PyMC 5.8 API gap blocks the ranking machinery (e.g. LOO/Pseudo-BMA+ bootstrap helpers), switch to `causality-handbook` and record the switch in the run log.
- Full package lists: `conda list -n bap3` / `conda list -n causality-handbook` (both name-addressable; no `-p` prefix needed for these two).
- Sampling is CPU-bound; no GPU required.
