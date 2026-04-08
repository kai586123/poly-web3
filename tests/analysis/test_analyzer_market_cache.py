import asyncio

from analysis_poly.analyzer import PolymarketProfitAnalyzer, _market_order_key
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
