from __future__ import annotations

import json
import re
from pathlib import Path

from .models import PolymarketMarket


class MarketMetadataCache:
    def __init__(self, cache_dir: str | Path = ".cache/market_by_slug", recent_window_sec: int = 30 * 60):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._recent_window_sec = recent_window_sec
        self._symbol_payload_cache: dict[str, dict] = {}
        self._market_obj_cache: dict[str, PolymarketMarket] = {}

    def is_cache_eligible(self, slug: str, now_ts: int) -> bool:
        market_ts = _market_ts_from_slug(slug)
        if market_ts is None:
            return False
        return (now_ts - market_ts) > self._recent_window_sec

    def get(self, slug: str) -> PolymarketMarket | None:
        cached_market = self._market_obj_cache.get(slug)
        if cached_market is not None:
            return cached_market

        symbol = _symbol_from_slug(slug)
        if symbol is None:
            return None

        payload = self._load_symbol_payload(symbol)
        markets = payload.get("markets", {})
        market_payload = markets.get(slug)
        if market_payload is not None:
            try:
                market = PolymarketMarket.model_validate(market_payload)
                self._market_obj_cache[slug] = market
                return market
            except Exception:  # noqa: BLE001
                return None

        # Backward compatibility for legacy per-slug cache files.
        legacy_path = self._legacy_path_for_slug(slug)
        if not legacy_path.exists():
            return None
        try:
            market = PolymarketMarket.model_validate_json(legacy_path.read_text(encoding="utf-8"))
            self._market_obj_cache[slug] = market
            self.set(slug, market)
            return market
        except Exception:  # noqa: BLE001
            return None

    def set(self, slug: str, market: PolymarketMarket) -> None:
        symbol = _symbol_from_slug(slug)
        if symbol is None:
            return

        payload = self._load_symbol_payload(symbol)
        market_dump = market.model_dump()
        payload["symbol"] = symbol
        markets = payload["markets"]
        if markets.get(slug) == market_dump:
            self._market_obj_cache[slug] = market
            return

        markets[slug] = market_dump
        self._market_obj_cache[slug] = market
        self._save_symbol_payload(symbol, payload)

    def _load_symbol_payload(self, symbol: str) -> dict:
        cached = self._symbol_payload_cache.get(symbol)
        if cached is not None:
            return cached

        path = self._path_for_symbol(symbol)
        payload: dict = {"symbol": symbol, "markets": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except Exception:  # noqa: BLE001
                payload = {"symbol": symbol, "markets": {}}

        if not isinstance(payload.get("markets"), dict):
            payload["markets"] = {}
        payload["symbol"] = symbol
        self._symbol_payload_cache[symbol] = payload
        return payload

    def _save_symbol_payload(self, symbol: str, payload: dict) -> None:
        path = self._path_for_symbol(symbol)
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except Exception:  # noqa: BLE001
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:  # noqa: BLE001
                pass
            return

    def _path_for_symbol(self, symbol: str) -> Path:
        safe_symbol = re.sub(r"[^a-zA-Z0-9_.-]", "_", symbol.lower())
        return self._cache_dir / f"{safe_symbol}.json"

    def _legacy_path_for_slug(self, slug: str) -> Path:
        safe_slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", slug)
        return self._cache_dir / f"{safe_slug}.json"



def _market_ts_from_slug(slug: str) -> int | None:
    try:
        return int(str(slug).rsplit("-", 1)[-1])
    except Exception:  # noqa: BLE001
        return None


def _symbol_from_slug(slug: str) -> str | None:
    parts = str(slug).split("-")
    if not parts:
        return None
    symbol = parts[0].strip().lower()
    return symbol or None
