from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .storage_paths import default_raw_api_cache_dir

RAW_API_CACHE_SCHEMA_VERSION = 1


def _safe_segment(value: str, max_len: int = 16) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]", "_", text)
    return text[:max_len] if len(text) > max_len else text or "x"


def _key_hash(parts: tuple[Any, ...]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RawPolymarketDataCache:
    """Disk cache for upstream API payloads only (Gamma market, trades, activity, fee-rate). Never stores analysis."""

    def __init__(self, cache_dir: str | Path | None = None):
        self._dir = Path(cache_dir) if cache_dir is not None else default_raw_api_cache_dir()
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, addr: str, key_hash: str) -> Path:
        return self._dir / f"{kind}_{_safe_segment(addr, 12)}_{key_hash[:20]}.json"

    def load_trade_pages(self, address: str, condition_id: str, taker_only: bool, page_limit: int) -> list[Any] | None:
        key = _key_hash((address.lower(), condition_id, taker_only, int(page_limit)))
        path = self._path("trades", address, key)
        return self._load_list_payload(path, "trades")

    def save_trade_pages(self, address: str, condition_id: str, taker_only: bool, page_limit: int, pages: list[Any]) -> None:
        key = _key_hash((address.lower(), condition_id, taker_only, int(page_limit)))
        path = self._path("trades", address, key)
        self._save_payload(path, {"kind": "trades", "records": pages})

    def load_activity_pages(self, address: str, condition_id: str, activity_type: str, page_limit: int) -> list[Any] | None:
        key = _key_hash((address.lower(), condition_id, str(activity_type).upper(), int(page_limit)))
        path = self._path("activity", address, key)
        return self._load_list_payload(path, "activity")

    def save_activity_pages(
        self, address: str, condition_id: str, activity_type: str, page_limit: int, pages: list[Any]
    ) -> None:
        key = _key_hash((address.lower(), condition_id, str(activity_type).upper(), int(page_limit)))
        path = self._path("activity", address, key)
        self._save_payload(path, {"kind": "activity", "records": pages})

    def load_fee_rate_raw(self, token_id: str) -> Any | None:
        key = _key_hash((str(token_id),))
        path = self._path("fee_rate", token_id, key)
        return self._load_raw_payload(path)

    def save_fee_rate_raw(self, token_id: str, raw: Any) -> None:
        key = _key_hash((str(token_id),))
        path = self._path("fee_rate", token_id, key)
        self._save_payload(path, {"kind": "fee_rate", "raw": raw})

    def load_gamma_market_by_slug_raw(self, slug: str) -> dict[str, Any] | None:
        key = _key_hash((str(slug).lower().strip(),))
        path = self._path("gamma_market", slug, key)
        return self._load_dict_raw_payload(path)

    def save_gamma_market_by_slug_raw(self, slug: str, raw: dict[str, Any]) -> None:
        key = _key_hash((str(slug).lower().strip(),))
        path = self._path("gamma_market", slug, key)
        self._save_payload(path, {"kind": "gamma_market", "raw": raw})

    def _load_list_payload(self, path: Path, expected_kind: str) -> list[Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if int(data.get("schema_version", 0)) != RAW_API_CACHE_SCHEMA_VERSION:
            return None
        if data.get("kind") != expected_kind:
            return None
        records = data.get("records")
        if not isinstance(records, list):
            return None
        return records

    def _load_raw_payload(self, path: Path) -> Any | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if int(data.get("schema_version", 0)) != RAW_API_CACHE_SCHEMA_VERSION:
            return None
        if data.get("kind") != "fee_rate":
            return None
        if "raw" not in data:
            return None
        return data["raw"]

    def _load_dict_raw_payload(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if int(data.get("schema_version", 0)) != RAW_API_CACHE_SCHEMA_VERSION:
            return None
        if data.get("kind") != "gamma_market":
            return None
        raw = data.get("raw")
        if not isinstance(raw, dict):
            return None
        return raw

    def _save_payload(self, path: Path, body: dict[str, Any]) -> None:
        payload = {"schema_version": RAW_API_CACHE_SCHEMA_VERSION, **body}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        except Exception:  # noqa: BLE001
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:  # noqa: BLE001
                pass
