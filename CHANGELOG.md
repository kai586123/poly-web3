# Changelog

## 1.2.3

- Analysis: optional on-disk **raw API cache** (`analysis_poly/raw_api_cache.py`, `default_raw_api_cache_dir`) for Gamma market, trades, activity, and CLOB fee-rate payloads; wire into `PolymarketApiClient`. Disable with `ANALYSIS_POLY_DISABLE_RAW_API_CACHE=1`.
- Analysis: **maker rebate** modeled path — stable `_trade_key` (rounded price/size) across separate `takerOnly` requests, dedupe duplicate trade rows, maker accrual gated by **fill UTC day** vs current day; `ANALYSIS_POLY_DISABLE_MAKER_REBATE=1` turns off modeled maker rebate on the net engine. Comments clarify rebates are not present in Data API trade JSON.
- Analyzer UI: fee-related status display (e.g. `StatusCard`); assorted fee / no-fee engine alignment and tests (`test_raw_api_cache`, profit engine trade-key/dedupe tests, `TokenReport.side` in filter-empty test).

## 1.2.2

- Analyzer: YES/NO side mapping on tokens and reports; overlay YES/NO PnL on the total curve; session analytics split into ALL / YES / NO with side-specific sessions (not only entry-side tagging).
- Analyzer: market result cache `schema_version` (v2) so stale cached sessions without `entry_side` are not reused.
- Tests: session analytics, profit engine side labeling, cache schema rejection.

## 1.2.1

- README: move optional pip uninstall instructions to section 一; renumber following sections.

## 1.2.0

- Add `requirements.txt` and `requirements-dev.txt`; document running from a clone (third-party deps only—no default `pip install -e .` for this repo).
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
