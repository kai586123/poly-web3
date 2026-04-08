from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .models import ActivityRecord, PolymarketMarket, TradeRecord


class PolymarketApiClient:
    def __init__(self, timeout_sec: float = 20, retries: int = 5):
        self._timeout_sec = timeout_sec
        self._retries = retries
        self._gamma_base = "https://gamma-api.polymarket.com"
        self._data_base = "https://data-api.polymarket.com"
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
        data = await self._request_json("GET", f"{self._gamma_base}/markets/slug/{slug}")
        if not data:
            return None

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
        )

    async def get_trades(
        self,
        user: str,
        market: str,
        taker_only: bool,
        limit: int = 1000,
    ) -> list[TradeRecord]:
        records: list[TradeRecord] = []
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
            page = [TradeRecord.model_validate(item) for item in data]
            records.extend(page)
            if len(page) < limit:
                break
            offset += len(page)
        return records

    async def get_activity(
        self,
        user: str,
        market: str,
        activity_type: str,
        limit: int = 1000,
    ) -> list[ActivityRecord]:
        records: list[ActivityRecord] = []
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
            page = [ActivityRecord.model_validate(item) for item in data]
            records.extend(page)
            if len(page) < limit:
                break
            offset += len(page)
        return records



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
