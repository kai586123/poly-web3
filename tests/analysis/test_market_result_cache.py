from analysis_poly.market_result_cache import AddressMarketResultCache


def test_address_market_result_cache_roundtrip(tmp_path):
    cache = AddressMarketResultCache(cache_dir=tmp_path / "result_cache")

    address = "0xe00740bce98a594e26861838885ab310ec3b548c"
    markets = {
        "btc-updown-15m-1771983900": {
            "market_slug": "btc-updown-15m-1771983900",
            "market_report": {"market_slug": "btc-updown-15m-1771983900"},
            "market_report_no_fee": {"market_slug": "btc-updown-15m-1771983900"},
            "deltas": [],
            "deltas_no_fee": [],
            "warnings": [],
        }
    }

    cache.save(address, markets)
    loaded = cache.load(address)

    assert "btc-updown-15m-1771983900" in loaded
    assert loaded["btc-updown-15m-1771983900"]["market_slug"] == "btc-updown-15m-1771983900"


def test_address_market_result_cache_missing_file_returns_empty(tmp_path):
    cache = AddressMarketResultCache(cache_dir=tmp_path / "result_cache")

    loaded = cache.load("0xabc")
    assert loaded == {}
