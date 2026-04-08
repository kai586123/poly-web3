from analysis_poly.market_cache import MarketMetadataCache
from analysis_poly.market_result_cache import AddressMarketResultCache
from analysis_poly.models import AnalysisRequest
from analysis_poly.storage_paths import (
    _repo_root_for_source_tree,
    default_cache_root,
    default_reports_dir,
)


def test_storage_paths_use_env_overrides(monkeypatch, tmp_path):
    cache_root = tmp_path / "cache-root"
    reports_root = tmp_path / "reports-root"
    monkeypatch.setenv("ANALYSIS_POLY_CACHE_DIR", str(cache_root))
    monkeypatch.setenv("ANALYSIS_POLY_REPORTS_DIR", str(reports_root))

    market_cache = MarketMetadataCache()
    result_cache = AddressMarketResultCache()

    assert market_cache._cache_dir == cache_root / "market_by_slug"
    assert result_cache._cache_dir == cache_root / "address_market_results"
    assert default_cache_root() == cache_root
    assert default_reports_dir() == reports_root


def test_analysis_request_defaults_to_stable_reports_dir(monkeypatch, tmp_path):
    reports_root = tmp_path / "reports-root"
    monkeypatch.setenv("ANALYSIS_POLY_REPORTS_DIR", str(reports_root))

    req = AnalysisRequest(
        address="0x3139bB6FE34b010dBEA552158eA36eF635E8096e",
        start_ts=1000,
        end_ts=2000,
        symbols=["btc"],
        intervals=[5],
    )

    assert req.output_dir == str(reports_root)


def test_storage_paths_default_to_repo_local_when_running_from_checkout():
    root = _repo_root_for_source_tree()
    assert root is not None
    assert (root / "pyproject.toml").is_file()

    cache = default_cache_root()
    reports = default_reports_dir()
    assert cache == (root / ".cache" / "poly-web3").resolve()
    assert reports == (root / ".data" / "poly-web3" / "reports").resolve()
