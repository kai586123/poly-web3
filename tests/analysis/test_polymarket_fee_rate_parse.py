"""Fee-rate JSON shapes from CLOB /fee-rate and caches."""

from unittest.mock import AsyncMock

import pytest

from analysis_poly.polymarket_client import PolymarketApiClient, _parse_fee_rate_response
from analysis_poly.raw_api_cache import RawPolymarketDataCache


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"base_fee": 30}, 30.0),
        ({"baseFee": 40}, 40.0),
        ({"fee_rate_bps": 72}, 72.0),
        ({"feeRateBps": 50}, 50.0),
        (72, 72.0),
        ("72", 72.0),
        ({}, None),
        ({"other": 1}, None),
    ],
)
def test_parse_fee_rate_response(payload, expected):
    assert _parse_fee_rate_response(payload) == expected


@pytest.mark.asyncio
async def test_get_fee_rate_bps_reads_base_fee_from_cache(tmp_path):
    token_id = "tok_base_fee"
    cache = RawPolymarketDataCache(cache_dir=tmp_path)
    cache.save_fee_rate_raw(token_id, {"base_fee": 30})

    client = PolymarketApiClient(raw_data_cache=cache)
    client._request_json = AsyncMock(side_effect=AssertionError("network should not be called"))  # type: ignore[method-assign]

    bps = await client.get_fee_rate_bps(token_id)
    assert bps == 30.0
    await client.aclose()
