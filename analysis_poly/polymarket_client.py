from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx

from .models import ActivityRecord, PolymarketMarket, TradeRecord

if TYPE_CHECKING:
    from .raw_api_cache import RawPolymarketDataCache


class PolymarketApiClient:
    def __init__(
        self,
        timeout_sec: float = 20,
        retries: int = 5,
        raw_data_cache: RawPolymarketDataCache | None = None,
    ):
        self._timeout_sec = timeout_sec
        self._retries = retries
        self._raw_data_cache = raw_data_cache
        self._gamma_base = "https://gamma-api.polymarket.com"
        self._data_base = "https://data-api.polymarket.com"
        self._clob_base = "https://clob.polymarket.com"
        self._client = httpx.AsyncClient(timeout=timeout_sec)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request_json(self, method: str, url: str, params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = await self._client.request(method, url, params=params)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if 400 <= exc.response.status_code < 500:
                    raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc

            if attempt + 1 < self._retries:
                await asyncio.sleep(0.4 * (2**attempt))

        if last_exc:
            raise last_exc
        raise RuntimeError("request failed without exception")

    async def get_market_by_slug(self, slug: str) -> PolymarketMarket | None:
        if self._raw_data_cache is not None:
            cached = self._raw_data_cache.load_gamma_market_by_slug_raw(slug)
            if cached is not None:
                return _polymarket_market_from_gamma_dict(cached)
        data = await self._request_json("GET", f"{self._gamma_base}/markets/slug/{slug}")
        if not data or not isinstance(data, dict):
            return None
        if self._raw_data_cache is not None:
            self._raw_data_cache.save_gamma_market_by_slug_raw(slug, data)
        return _polymarket_market_from_gamma_dict(data)

    async def get_fee_rate_bps(self, token_id: str) -> float | None:
        if not token_id:
            return None
        if self._raw_data_cache is not None:
            cached_raw = self._raw_data_cache.load_fee_rate_raw(token_id)
            if cached_raw is not None:
                return _parse_fee_rate_response(cached_raw)
        data = await self._request_json(
            "GET",
            f"{self._clob_base}/fee-rate",
            params={"token_id": token_id},
        )
        if data is not None and self._raw_data_cache is not None:
            self._raw_data_cache.save_fee_rate_raw(token_id, data)
        return _parse_fee_rate_response(data)

    async def get_trades(
        self,
        user: str,
        market: str,
        taker_only: bool,
        limit: int = 1000,
    ) -> list[TradeRecord]:
        if self._raw_data_cache is not None:
            cached = self._raw_data_cache.load_trade_pages(user, market, taker_only, limit)
            if cached is not None:
                return [TradeRecord.model_validate(item) for item in cached]

        records: list[TradeRecord] = []
        raw_flat: list[Any] = []
        offset = 0
        while True:
            params = {
                "user": user,
                "market": market,
                "takerOnly": str(taker_only).lower(),
                "limit": limit,
                "offset": offset,
            }
            data = await self._request_json("GET", f"{self._data_base}/trades", params=params)
            if not data:
                break
            if isinstance(data, list):
                raw_flat.extend(data)
            page = [TradeRecord.model_validate(item) for item in data]
            records.extend(page)
            if len(page) < limit:
                break
            offset += len(page)
        if self._raw_data_cache is not None:
            self._raw_data_cache.save_trade_pages(user, market, taker_only, limit, raw_flat)
        return records

    async def get_activity(
        self,
        user: str,
        market: str,
        activity_type: str,
        limit: int = 1000,
    ) -> list[ActivityRecord]:
        if self._raw_data_cache is not None:
            cached = self._raw_data_cache.load_activity_pages(user, market, activity_type, limit)
            if cached is not None:
                return [ActivityRecord.model_validate(item) for item in cached]

        records: list[ActivityRecord] = []
        raw_flat: list[Any] = []
        offset = 0
        while True:
            params = {
                "user": user,
                "market": market,
                "type": activity_type,
                "sortBy": "TIMESTAMP",
                "sortDirection": "ASC",
                "limit": limit,
                "offset": offset,
            }
            data = await self._request_json("GET", f"{self._data_base}/activity", params=params)
            if not data:
                break
            if isinstance(data, list):
                raw_flat.extend(data)
            page = [ActivityRecord.model_validate(item) for item in data]
            records.extend(page)
            if len(page) < limit:
                break
            offset += len(page)
        if self._raw_data_cache is not None:
            self._raw_data_cache.save_activity_pages(user, market, activity_type, limit, raw_flat)
        return records



def _polymarket_market_from_gamma_dict(data: dict[str, Any]) -> PolymarketMarket | None:
    outcomes_raw = data.get("outcomes", "[]")
    outcome_prices_raw = data.get("outcomePrices", "[]")
    tokens_raw = data.get("clobTokenIds", "[]")

    outcomes = _parse_json_field(outcomes_raw, fallback=[])
    outcome_prices = [float(x) for x in _parse_json_field(outcome_prices_raw, fallback=[])]
    token_ids = [str(x) for x in _parse_json_field(tokens_raw, fallback=[])]

    if len(token_ids) < 2:
        return None

    return PolymarketMarket(
        slug=data["slug"],
        condition_id=data["conditionId"],
        up_token_id=token_ids[0],
        down_token_id=token_ids[1],
        outcomes=outcomes,
        outcome_prices=outcome_prices,
        closed=bool(data.get("closed", False)),
        fees_enabled=(
            bool(data.get("feesEnabled"))
            if data.get("feesEnabled") is not None
            else None
        ),
        category=(str(data.get("category")).strip() if data.get("category") is not None else None),
    )


def _parse_json_field(raw: Any, fallback: list[Any]) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            return fallback
        except Exception:  # noqa: BLE001
            return fallback
    return fallback


def _to_float_or_none(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _parse_fee_rate_response(data: Any) -> float | None:
    if data is None:
        return None
    if isinstance(data, (int, float, str)):
        return _to_float_or_none(data)
    if isinstance(data, dict):
        for key in ("fee_rate_bps", "feeRateBps", "taker_fee_rate_bps", "takerFeeRateBps"):
            if key in data:
                return _to_float_or_none(data[key])
    return None
