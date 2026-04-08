# Changelog

## 1.2.0

- Add `requirements.txt` and `requirements-dev.txt`; document running from a clone with `PYTHONPATH` (third-party deps only—no default `pip install -e .` for this repo).
- Add `scripts/analysis-poly` and `scripts/analysis-poly-open` wrappers for the analyzer CLI.
- Analyzer cache/report defaults: stable paths when running from a source checkout (`analysis_poly/storage_paths.py`); tests updated.

## 1.1.0

- Monorepo: bundle `analysis_poly` (profit web analyzer) and `poly_position_watcher` (position utilities) with the `poly_web3` SDK in a single `pip install -e .` from this repository.
- Merged tooling: one `pyproject.toml`, shared `tests/` layout (`sdk`, `analysis`, `watcher`), root `frontend/` + `npm run build` for dashboard assets, console scripts `analysis-poly` / `analysis-poly-open`.
- Removed PyPI-only `poly-web3[analysis]` extra; use a git checkout for the full stack.

## 1.0.7

- Refactor HTTP requests into a dedicated API client with URL constants and shared `requests.Session` usage.
- Add batch `split_batch` and `merge_batch` APIs with per-market amounts, `negative_risk` grouping, and configurable `batch_size`.
- Update `merge_all` to use batch merge execution, honor `min_usdc` explicitly, and document the new workflow in examples and README files.

## 1.0.6

- Add NegRisk Adapter split/merge support for binary negative-risk markets.
- Auto-detect `negRisk` markets through the Gamma markets API and route split/merge accordingly.
- Add regression tests for neg-risk split/merge routing.

## 1.0.1

- Fix web3 7.x compatibility for calldata encoding and checksum helpers.
- Keep redeem flow compatible across web3 6/7 in proxy and base services.
