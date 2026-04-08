from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSlugSpec:
    symbol: str
    interval: int
    timestamp: int

    @property
    def slug(self) -> str:
        return f"{self.symbol}-updown-{self.interval}m-{self.timestamp}"


def generate_market_slug_specs(
    symbols: list[str], intervals: list[int], start_ts: int, end_ts: int
) -> list[MarketSlugSpec]:
    specs: list[MarketSlugSpec] = []
    for symbol in symbols:
        for interval in intervals:
            step = interval * 60
            first_ts = math.ceil(start_ts / step) * step
            ts = first_ts
            while ts < end_ts:
                specs.append(MarketSlugSpec(symbol=symbol, interval=interval, timestamp=ts))
                ts += step
    specs.sort(key=lambda s: (s.timestamp, s.symbol, s.interval))
    return specs
