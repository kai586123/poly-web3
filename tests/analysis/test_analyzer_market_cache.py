import asyncio

from analysis_poly.analyzer import (
    PolymarketProfitAnalyzer,
    _market_order_key,
    _normalize_fee_rate_bps,
    _result_from_cache_payload,
)
from analysis_poly.market_cache import MarketMetadataCache
from analysis_poly.models import PolymarketMarket


class _FakeClient:
    def __init__(self):
        self.calls = 0

    async def get_market_by_slug(self, slug: str):
        self.calls += 1
        return PolymarketMarket(
            slug=slug,
            condition_id=f"cond_{slug}",
            up_token_id=f"up_{slug}",
            down_token_id=f"down_{slug}",
            outcomes=["Up", "Down"],
            outcome_prices=[1.0, 0.0],
        )


class _FailFeeRateClient:
    async def get_fee_rate_bps(self, _token_id: str):
        raise RuntimeError("fee endpoint down")


def test_fetch_market_with_cache_uses_local_file(tmp_path):
    async def runner():
        analyzer = PolymarketProfitAnalyzer()
        analyzer._market_cache = MarketMetadataCache(
            cache_dir=tmp_path / "market_cache",
            recent_window_sec=1800,
        )
        client = _FakeClient()

        old_slug = "btc-updown-15m-1000"
        market1 = await analyzer._fetch_market_with_cache(client, old_slug)
        market2 = await analyzer._fetch_market_with_cache(client, old_slug)

        assert market1 is not None
        assert market2 is not None
        assert market1.slug == old_slug
        assert client.calls == 1

    asyncio.run(runner())


def test_fetch_market_with_cache_skips_recent_window(tmp_path):
    async def runner():
        analyzer = PolymarketProfitAnalyzer()
        analyzer._market_cache = MarketMetadataCache(
            cache_dir=tmp_path / "market_cache",
            recent_window_sec=10**12,
        )
        client = _FakeClient()

        slug = "btc-updown-15m-9999999999"
        await analyzer._fetch_market_with_cache(client, slug)
        await analyzer._fetch_market_with_cache(client, slug)

        assert client.calls == 2

    asyncio.run(runner())


def test_market_order_key_uses_slug_timestamp():
    assert _market_order_key("btc-updown-5m-100") < _market_order_key("btc-updown-5m-200")
    # Invalid slug timestamps should be pushed to the end.
    assert _market_order_key("invalid-slug")[0] > 10**10


def test_result_cache_payload_rejects_old_schema():
    payload = {
        "market_slug": "btc-updown-5m-1000",
        "market_report": {"market_slug": "btc-updown-5m-1000"},
        "market_report_no_fee": {"market_slug": "btc-updown-5m-1000"},
        "deltas": [],
        "deltas_no_fee": [],
        "warnings": [],
        "trade_sessions": [],
        "session_diagnostics": {},
    }

    assert _result_from_cache_payload("btc-updown-5m-1000", payload) is None


def test_fee_rate_fallback_uses_crypto_default():
    async def runner():
        analyzer = PolymarketProfitAnalyzer()
        market = PolymarketMarket(
            slug="btc-updown-5m-1000",
            condition_id="cond_1",
            up_token_id="up_token",
            down_token_id="down_token",
            outcomes=["Up", "Down"],
            outcome_prices=[0.5, 0.5],
            fees_enabled=True,
        )
        rates, warnings = await analyzer._resolve_market_fee_rate_bps_by_token(
            client=_FailFeeRateClient(),
            market=market,
            fallback_fee_rate_bps=1000.0,
            fee_rate_bps_cache={},
        )

        assert rates["up_token"] == 72.0
        assert rates["down_token"] == 72.0
        fallback_warnings = [w for w in warnings if w.code == "FEE_RATE_FALLBACK"]
        assert len(fallback_warnings) == 2
        assert all("fallback fee_rate_bps=72.0" in w.message for w in fallback_warnings)

    asyncio.run(runner())


def test_normalize_fee_rate_bps_uses_category_default_for_large_values():
    assert _normalize_fee_rate_bps(1000.0, 72.0) == 72.0
    assert _normalize_fee_rate_bps(1000.0, 40.0) == 40.0


def test_normalize_fee_rate_bps_accepts_expected_ranges():
    assert _normalize_fee_rate_bps(72.0, 40.0) == 72.0
    assert _normalize_fee_rate_bps(0.072, 40.0) == 72.0
