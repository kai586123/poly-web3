from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from analysis_poly.polymarket_client import PolymarketApiClient
from analysis_poly.raw_api_cache import RawPolymarketDataCache


@pytest.mark.asyncio
async def test_get_trades_uses_disk_cache_without_http(tmp_path):
    user = "0xabc"
    market = "0xcond"
    raw_item = {
        "transactionHash": "0x1",
        "timestamp": 1,
        "side": "BUY",
        "asset": "tok",
        "conditionId": market,
        "size": 1.0,
        "price": 0.5,
    }
    cache = RawPolymarketDataCache(cache_dir=tmp_path)
    cache.save_trade_pages(user, market, True, 1000, [raw_item])

    client = PolymarketApiClient(raw_data_cache=cache)
    client._request_json = AsyncMock(side_effect=AssertionError("network should not be called"))  # type: ignore[method-assign]

    rows = await client.get_trades(user, market, taker_only=True, limit=1000)
    assert len(rows) == 1
    assert rows[0].transaction_hash == "0x1"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_fee_rate_bps_uses_disk_cache_without_http(tmp_path):
    cache = RawPolymarketDataCache(cache_dir=tmp_path)
    token_id = "12345"
    cache.save_fee_rate_raw(token_id, {"fee_rate_bps": 72})

    client = PolymarketApiClient(raw_data_cache=cache)
    client._request_json = AsyncMock(side_effect=AssertionError("network should not be called"))  # type: ignore[method-assign]

    bps = await client.get_fee_rate_bps(token_id)
    assert bps == 72.0
    await client.aclose()


@pytest.mark.asyncio
async def test_get_market_by_slug_uses_disk_cache_without_http(tmp_path):
    slug = "test-market"
    raw = {
        "slug": slug,
        "conditionId": "0xc",
        "clobTokenIds": '["a","b"]',
        "outcomes": '["Yes","No"]',
        "outcomePrices": "[0.5,0.5]",
        "closed": False,
        "category": "crypto",
    }
    cache = RawPolymarketDataCache(cache_dir=tmp_path)
    cache.save_gamma_market_by_slug_raw(slug, raw)

    client = PolymarketApiClient(raw_data_cache=cache)
    client._request_json = AsyncMock(side_effect=AssertionError("network should not be called"))  # type: ignore[method-assign]

    m = await client.get_market_by_slug(slug)
    assert m is not None
    assert m.slug == slug
    assert m.up_token_id == "a"
    await client.aclose()
