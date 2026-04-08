from analysis_poly.market_cache import MarketMetadataCache
from analysis_poly.models import PolymarketMarket


def test_market_cache_eligibility():
    cache = MarketMetadataCache(cache_dir=".cache/test_market_cache_eligibility", recent_window_sec=1800)

    assert cache.is_cache_eligible("btc-updown-15m-1000", now_ts=4000)
    assert not cache.is_cache_eligible("btc-updown-15m-3500", now_ts=4000)
    assert not cache.is_cache_eligible("invalid-slug", now_ts=4000)


def test_market_cache_set_get_roundtrip(tmp_path):
    cache = MarketMetadataCache(cache_dir=tmp_path / "market_cache", recent_window_sec=1800)

    market = PolymarketMarket(
        slug="btc-updown-15m-1000",
        condition_id="cond",
        up_token_id="up",
        down_token_id="down",
        outcomes=["Up", "Down"],
        outcome_prices=[1.0, 0.0],
    )
    cache.set(market.slug, market)

    loaded = cache.get(market.slug)
    assert loaded is not None
    assert loaded.slug == market.slug
    assert loaded.condition_id == "cond"


def test_market_cache_grouped_by_symbol_file(tmp_path):
    cache = MarketMetadataCache(cache_dir=tmp_path / "market_cache", recent_window_sec=1800)
    market_a = PolymarketMarket(
        slug="btc-updown-15m-1000",
        condition_id="cond_a",
        up_token_id="up_a",
        down_token_id="down_a",
        outcomes=["Up", "Down"],
        outcome_prices=[1.0, 0.0],
    )
    market_b = PolymarketMarket(
        slug="btc-updown-15m-2000",
        condition_id="cond_b",
        up_token_id="up_b",
        down_token_id="down_b",
        outcomes=["Up", "Down"],
        outcome_prices=[1.0, 0.0],
    )

    cache.set(market_a.slug, market_a)
    cache.set(market_b.slug, market_b)

    files = sorted((tmp_path / "market_cache").glob("*.json"))
    assert len(files) == 1
    assert files[0].name == "btc.json"
    assert cache.get(market_a.slug) is not None
    assert cache.get(market_b.slug) is not None


def test_market_cache_get_uses_in_memory_symbol_payload(tmp_path):
    cache = MarketMetadataCache(cache_dir=tmp_path / "market_cache", recent_window_sec=1800)
    market = PolymarketMarket(
        slug="btc-updown-15m-3000",
        condition_id="cond",
        up_token_id="up",
        down_token_id="down",
        outcomes=["Up", "Down"],
        outcome_prices=[1.0, 0.0],
    )
    cache.set(market.slug, market)

    loaded_first = cache.get(market.slug)
    assert loaded_first is not None

    cache_file = tmp_path / "market_cache" / "btc.json"
    cache_file.unlink()

    loaded_second = cache.get(market.slug)
    assert loaded_second is not None
    assert loaded_second.slug == market.slug
