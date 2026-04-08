from analysis_poly.analyzer import _chunk_specs_by_timestamp, _is_market_result_cache_eligible
from analysis_poly.slugs import MarketSlugSpec


def test_chunk_specs_by_timestamp_keeps_same_timestamp_together():
    specs = [
        MarketSlugSpec(symbol="btc", interval=5, timestamp=100),
        MarketSlugSpec(symbol="eth", interval=5, timestamp=100),
        MarketSlugSpec(symbol="btc", interval=5, timestamp=200),
        MarketSlugSpec(symbol="eth", interval=5, timestamp=200),
        MarketSlugSpec(symbol="btc", interval=5, timestamp=300),
    ]

    chunks = _chunk_specs_by_timestamp(specs, timestamps_per_chunk=2)

    assert len(chunks) == 2
    assert [s.timestamp for s in chunks[0]] == [100, 100, 200, 200]
    assert [s.timestamp for s in chunks[1]] == [300]


def test_chunk_specs_by_timestamp_min_chunk_size_one():
    specs = [
        MarketSlugSpec(symbol="btc", interval=5, timestamp=100),
        MarketSlugSpec(symbol="btc", interval=5, timestamp=200),
    ]

    chunks = _chunk_specs_by_timestamp(specs, timestamps_per_chunk=0)

    assert len(chunks) == 2
    assert [s.timestamp for s in chunks[0]] == [100]
    assert [s.timestamp for s in chunks[1]] == [200]


def test_market_result_cache_eligibility_recent_window():
    # market timestamp very old -> eligible
    assert _is_market_result_cache_eligible("btc-updown-5m-1000", now_ts=4000, recent_window_sec=1800)
    # market timestamp inside recent window -> not eligible
    assert not _is_market_result_cache_eligible("btc-updown-5m-3500", now_ts=4000, recent_window_sec=1800)
    # invalid slug -> not eligible
    assert not _is_market_result_cache_eligible("invalid-slug", now_ts=4000, recent_window_sec=1800)
