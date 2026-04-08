from __future__ import annotations

import json
import re
import time
from pathlib import Path


class AddressMarketResultCache:
    def __init__(self, cache_dir: str | Path = ".cache/address_market_results"):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self, address: str) -> dict[str, dict]:
        path = self._path_for_address(address)
        if not path.exists():
            return {}

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            markets = payload.get("markets")
            if isinstance(markets, dict):
                return markets
        except Exception:  # noqa: BLE001
            return {}
        return {}

    def save(self, address: str, markets: dict[str, dict]) -> None:
        path = self._path_for_address(address)
        payload = {
            "address": address.lower(),
            "updated_at": int(time.time()),
            "markets": markets,
        }

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

    def _path_for_address(self, address: str) -> Path:
        safe_addr = re.sub(r"[^a-zA-Z0-9_.-]", "_", address.lower().strip())
        return self._cache_dir / f"{safe_addr}.json"
