from __future__ import annotations

import asyncio
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from datetime import datetime, timezone

from loguru import logger

from .market_cache import MarketMetadataCache
from .market_result_cache import AddressMarketResultCache
from .models import (
    AnalysisReport,
    AnalysisRequest,
    CurvePoint,
    MarketReport,
    MarketScatterPoint,
    PolymarketMarket,
    SummaryStats,
    TradeRecord,
    WarningItem,
)
from .polymarket_client import PolymarketApiClient
from .profit_engine import PnlDelta, ProfitEngine, build_curve
from .slugs import MarketSlugSpec, generate_market_slug_specs

MARKET_FETCH_CONCURRENCY_DEFAULT = 10
MARKET_TIMESTAMP_CHUNK_SIZE_DEFAULT = 20
MARKET_RESULT_CACHE_RECENT_WINDOW_SEC = 30 * 60


@dataclass
class _MarketProcessResult:
    market_slug: str
    market_report: MarketReport
    market_report_no_fee: MarketReport
    deltas: list[PnlDelta]
    deltas_no_fee: list[PnlDelta]
    warnings: list[WarningItem]
    cache_updated: bool = False
    scatter_point: MarketScatterPoint | None = None


class AnalyzerHooks(Protocol):
    async def on_run_started(self, total_markets: int) -> None: ...

    async def on_progress(self, current: int, total: int, market_slug: str) -> None: ...

    async def on_warning(self, warning: WarningItem) -> None: ...

    async def on_total_point(self, timestamp: int, delta: float, cumulative: float) -> None: ...

    async def on_market_point(
        self, market_slug: str, timestamp: int, delta: float, cumulative: float
    ) -> None: ...

    async def on_total_point_no_fee(self, timestamp: int, delta: float, cumulative: float) -> None: ...

    async def on_market_point_no_fee(
        self, market_slug: str, timestamp: int, delta: float, cumulative: float
    ) -> None: ...


class NullHooks:
    async def on_run_started(self, total_markets: int) -> None:
        return

    async def on_progress(self, current: int, total: int, market_slug: str) -> None:
        return

    async def on_warning(self, warning: WarningItem) -> None:
        return

    async def on_total_point(self, timestamp: int, delta: float, cumulative: float) -> None:
        return

    async def on_market_point(
        self, market_slug: str, timestamp: int, delta: float, cumulative: float
    ) -> None:
        return

    async def on_total_point_no_fee(self, timestamp: int, delta: float, cumulative: float) -> None:
        return

    async def on_market_point_no_fee(
        self, market_slug: str, timestamp: int, delta: float, cumulative: float
    ) -> None:
        return


class PolymarketProfitAnalyzer:
    def __init__(self):
        self._market_cache = MarketMetadataCache()
        self._market_result_cache = AddressMarketResultCache()
        self._market_fetch_concurrency = MARKET_FETCH_CONCURRENCY_DEFAULT
        self._timestamp_chunk_size = MARKET_TIMESTAMP_CHUNK_SIZE_DEFAULT

    async def run(
        self,
        req: AnalysisRequest,
        stop_event: asyncio.Event | None = None,
        hooks: AnalyzerHooks | None = None,
    ) -> AnalysisReport:
        stop_event = stop_event or asyncio.Event()
        hooks = hooks or NullHooks()

        client = PolymarketApiClient(timeout_sec=req.request_timeout_sec)
        engine = ProfitEngine(
            fee_rate_bps=req.fee_rate_bps,
            maker_reward_ratio=req.maker_reward_ratio,
            missing_cost_warn_qty=req.missing_cost_warn_qty,
        )
        engine_no_fee = ProfitEngine(
            fee_rate_bps=req.fee_rate_bps,
            maker_reward_ratio=req.maker_reward_ratio,
            missing_cost_warn_qty=req.missing_cost_warn_qty,
            charge_taker_fee=False,
        )

        all_warnings: list[WarningItem] = []
        market_reports: list[MarketReport] = []
        market_scatter_points: list[MarketScatterPoint] = []
        total_deltas: list[PnlDelta] = []
        total_deltas_no_fee: list[PnlDelta] = []
        market_deltas: dict[str, list[PnlDelta]] = defaultdict(list)
        market_deltas_no_fee: dict[str, list[PnlDelta]] = defaultdict(list)

        total_by_ts: dict[int, float] = defaultdict(float)
        market_by_ts: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        total_by_ts_no_fee: dict[int, float] = defaultdict(float)
        market_by_ts_no_fee: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        address_market_cache = self._market_result_cache.load(req.address)
        result_cache_dirty = False

        try:
            specs = generate_market_slug_specs(req.symbols, req.intervals, req.start_ts, req.end_ts)
            total_markets = len(specs)
            spec_chunks = _chunk_specs_by_timestamp(specs, self._timestamp_chunk_size)
            logger.info(
                "analyzer prepared spec_count={} timestamp_chunks={} market_fetch_concurrency={} process_concurrency={}",
                len(specs),
                len(spec_chunks),
                self._market_fetch_concurrency,
                max(1, req.concurrency),
            )
            await hooks.on_run_started(total_markets)

            process_concurrency = max(1, req.concurrency)
            processed_count = 0

            for spec_chunk in spec_chunks:
                if stop_event.is_set():
                    break

                chunk_slugs = [s.slug for s in spec_chunk]
                chunk_fetch_results = await self._fetch_markets_with_status(
                    client,
                    chunk_slugs,
                    self._market_fetch_concurrency,
                )
                chunk_markets = [market for _, market in chunk_fetch_results if market is not None]
                chunk_markets.sort(key=lambda m: _market_order_key(m.slug))

                for batch_start in range(0, len(chunk_markets), process_concurrency):
                    if stop_event.is_set():
                        break

                    batch_markets = chunk_markets[batch_start : batch_start + process_concurrency]
                    batch_results = await asyncio.gather(
                        *(
                            self._process_single_market(
                                client=client,
                                engine=engine,
                                engine_no_fee=engine_no_fee,
                                address=req.address,
                                address_market_cache=address_market_cache,
                                req=req,
                                market=market,
                            )
                            for market in batch_markets
                        )
                    )
                    # Keep push order stable by market timestamp inside one concurrent batch.
                    batch_results.sort(key=lambda x: _market_order_key(x.market_slug))

                    for result in batch_results:
                        if stop_event.is_set():
                            break

                        processed_count += 1
                        has_trade_activity = _has_market_trade_activity(result.market_report)
                        if has_trade_activity:
                            market_reports.append(result.market_report)
                            if result.scatter_point is not None:
                                market_scatter_points.append(result.scatter_point)
                            total_deltas.extend(result.deltas)
                            total_deltas_no_fee.extend(result.deltas_no_fee)
                            if result.deltas:
                                market_deltas[result.market_slug].extend(result.deltas)
                            if result.deltas_no_fee:
                                market_deltas_no_fee[result.market_slug].extend(result.deltas_no_fee)
                        else:
                            logger.debug("skip market without trades in output slug={}", result.market_slug)

                        for warning in result.warnings:
                            all_warnings.append(warning)
                            await hooks.on_warning(warning)
                        if result.cache_updated:
                            result_cache_dirty = True

                        for delta in result.deltas:
                            total_by_ts[delta.timestamp] += delta.delta_pnl_usdc
                            market_by_ts[delta.market_slug][delta.timestamp] += delta.delta_pnl_usdc

                            total_cumulative = _cumulative_at(total_by_ts, delta.timestamp)
                            market_cumulative = _cumulative_at(market_by_ts[delta.market_slug], delta.timestamp)

                            await hooks.on_total_point(
                                delta.timestamp,
                                delta.delta_pnl_usdc,
                                total_cumulative,
                            )
                            await hooks.on_market_point(
                                delta.market_slug,
                                delta.timestamp,
                                delta.delta_pnl_usdc,
                                market_cumulative,
                            )

                        for delta in result.deltas_no_fee:
                            total_by_ts_no_fee[delta.timestamp] += delta.delta_pnl_usdc
                            market_by_ts_no_fee[delta.market_slug][delta.timestamp] += delta.delta_pnl_usdc

                            total_cumulative_no_fee = _cumulative_at(total_by_ts_no_fee, delta.timestamp)
                            market_cumulative_no_fee = _cumulative_at(
                                market_by_ts_no_fee[delta.market_slug], delta.timestamp
                            )

                            await hooks.on_total_point_no_fee(
                                delta.timestamp,
                                delta.delta_pnl_usdc,
                                total_cumulative_no_fee,
                            )
                            await hooks.on_market_point_no_fee(
                                delta.market_slug,
                                delta.timestamp,
                                delta.delta_pnl_usdc,
                                market_cumulative_no_fee,
                            )

                        await hooks.on_progress(processed_count, total_markets, result.market_slug)

                missing_count = sum(1 for _, market in chunk_fetch_results if market is None)
                if missing_count > 0:
                    processed_count += missing_count
                    await hooks.on_progress(processed_count, total_markets, chunk_slugs[-1])

            total_curve = [
                CurvePoint(
                    timestamp=ts,
                    delta_realized_pnl_usdc=round(delta, 10),
                    cumulative_realized_pnl_usdc=round(cum, 10),
                )
                for ts, delta, cum in build_curve(total_deltas)
            ]

            market_curves: dict[str, list[CurvePoint]] = {}
            for market_slug, deltas in market_deltas.items():
                if not deltas:
                    continue
                market_curves[market_slug] = [
                    CurvePoint(
                        timestamp=ts,
                        delta_realized_pnl_usdc=round(delta, 10),
                        cumulative_realized_pnl_usdc=round(cum, 10),
                    )
                    for ts, delta, cum in build_curve(deltas)
                ]

            total_curve_no_fee = [
                CurvePoint(
                    timestamp=ts,
                    delta_realized_pnl_usdc=round(delta, 10),
                    cumulative_realized_pnl_usdc=round(cum, 10),
                )
                for ts, delta, cum in build_curve(total_deltas_no_fee)
            ]

            market_curves_no_fee: dict[str, list[CurvePoint]] = {}
            for market_slug, deltas in market_deltas_no_fee.items():
                if not deltas:
                    continue
                market_curves_no_fee[market_slug] = [
                    CurvePoint(
                        timestamp=ts,
                        delta_realized_pnl_usdc=round(delta, 10),
                        cumulative_realized_pnl_usdc=round(cum, 10),
                    )
                    for ts, delta, cum in build_curve(deltas)
                ]

            summary = SummaryStats(
                total_realized_pnl_usdc=round(sum(m.realized_pnl_usdc for m in market_reports), 10),
                total_taker_fee_usdc=round(sum(m.taker_fee_usdc for m in market_reports), 10),
                total_maker_reward_usdc=round(sum(m.maker_reward_usdc for m in market_reports), 10),
                markets_total=total_markets,
                markets_processed=len(market_reports),
            )

            report = AnalysisReport(
                request=req,
                summary=summary,
                markets=sorted(market_reports, key=lambda x: x.market_slug),
                total_curve=total_curve,
                market_curves=market_curves,
                total_curve_no_fee=total_curve_no_fee,
                market_curves_no_fee=market_curves_no_fee,
                warnings=all_warnings,
                is_partial=stop_event.is_set() and len(market_reports) < total_markets,
                hourly_realized_pnl_usdc=_build_hourly_pnl_buckets(total_deltas),
                market_scatter=sorted(market_scatter_points, key=lambda x: x.market_slug),
            )

            return report
        finally:
            if result_cache_dirty:
                try:
                    self._market_result_cache.save(req.address, address_market_cache)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("market result cache save failed address={} error={}", req.address, exc)
            await client.aclose()

    async def _fetch_markets_with_status(
        self,
        client: PolymarketApiClient,
        slugs: list[str],
        concurrency: int,
    ) -> list[tuple[str, object | None]]:
        sem = asyncio.Semaphore(max(1, concurrency))

        async def fetch(slug: str):
            async with sem:
                market = await self._fetch_market_with_cache(client, slug)
                return slug, market

        return await asyncio.gather(*(fetch(s) for s in slugs))

    async def _fetch_market_with_cache(
        self,
        client: PolymarketApiClient,
        slug: str,
    ):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        use_cache = self._market_cache.is_cache_eligible(slug, now_ts=now_ts)

        if use_cache:
            cached = self._market_cache.get(slug)
            if cached is not None:
                logger.debug("market cache hit slug={}", slug)
                return cached

        market = await client.get_market_by_slug(slug)
        if market is None:
            logger.warning("market not found slug={}", slug)
            return None

        if market is not None and use_cache:
            self._market_cache.set(slug, market)
            logger.debug("market cache write slug={}", slug)

        return market

    async def _process_single_market(
        self,
        client: PolymarketApiClient,
        engine: ProfitEngine,
        engine_no_fee: ProfitEngine,
        address: str,
        address_market_cache: dict[str, dict],
        req: AnalysisRequest,
        market,
    ) -> _MarketProcessResult:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        use_result_cache = _is_market_result_cache_eligible(
            market.slug,
            now_ts=now_ts,
            recent_window_sec=MARKET_RESULT_CACHE_RECENT_WINDOW_SEC,
        )

        if use_result_cache:
            cached_payload = address_market_cache.get(market.slug)
            if cached_payload is not None:
                cached_result = _result_from_cache_payload(market.slug, cached_payload)
                if cached_result is not None:
                    logger.debug("market result cache hit address={} slug={}", address, market.slug)
                    return cached_result
                logger.warning("market result cache invalid address={} slug={}", address, market.slug)

        taker_trades, all_trades, split_acts, redeem_acts = await asyncio.gather(
            client.get_trades(req.address, market.condition_id, True, req.page_limit),
            client.get_trades(req.address, market.condition_id, False, req.page_limit),
            client.get_activity(req.address, market.condition_id, "SPLIT", req.page_limit),
            client.get_activity(req.address, market.condition_id, "REDEEM", req.page_limit),
        )

        market_report, deltas, warnings = engine.process_market(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_acts,
            redeem_activities=redeem_acts,
        )
        market_report_no_fee, deltas_no_fee, _ = engine_no_fee.process_market(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_acts,
            redeem_activities=redeem_acts,
        )
        scatter_point = None
        if _has_market_trade_activity(market_report):
            scatter_point = _compute_market_scatter_point(
                market=market,
                all_trades=all_trades,
                market_report=market_report,
            )
        result = _MarketProcessResult(
            market_slug=market.slug,
            market_report=market_report,
            market_report_no_fee=market_report_no_fee,
            deltas=deltas,
            deltas_no_fee=deltas_no_fee,
            warnings=warnings,
            scatter_point=scatter_point,
        )
        if use_result_cache:
            new_payload = _result_to_cache_payload(result)
            if address_market_cache.get(market.slug) != new_payload:
                address_market_cache[market.slug] = new_payload
                result.cache_updated = True
        return result

    def save_json(self, report: AnalysisReport, path: str | None = None) -> str:
        output_dir = Path(report.request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not path:
            suffix = "partial" if report.is_partial else "final"
            path = str(output_dir / f"pnl_summary_{suffix}.json")

        Path(path).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_total_curve_csv(self, report: AnalysisReport, path: str | None = None) -> str:
        output_dir = Path(report.request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not path:
            suffix = "partial" if report.is_partial else "final"
            path = str(output_dir / f"pnl_total_curve_{suffix}.csv")

        with Path(path).open("w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(["timestamp", "delta_realized_pnl_usdc", "cumulative_realized_pnl_usdc"])
            for p in report.total_curve:
                writer.writerow([p.timestamp, p.delta_realized_pnl_usdc, p.cumulative_realized_pnl_usdc])
        return path

    def save_market_curve_csv(self, report: AnalysisReport, path: str | None = None) -> str:
        output_dir = Path(report.request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not path:
            suffix = "partial" if report.is_partial else "final"
            path = str(output_dir / f"pnl_market_curve_{suffix}.csv")

        with Path(path).open("w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(
                [
                    "market_slug",
                    "timestamp",
                    "delta_realized_pnl_usdc",
                    "cumulative_realized_pnl_usdc",
                ]
            )
            for market_slug, points in report.market_curves.items():
                for p in points:
                    writer.writerow(
                        [
                            market_slug,
                            p.timestamp,
                            p.delta_realized_pnl_usdc,
                            p.cumulative_realized_pnl_usdc,
                        ]
                    )
        return path

    def save_curve_csv(self, report: AnalysisReport, path: str | None = None) -> str:
        return self.save_total_curve_csv(report, path)



def _build_hourly_pnl_buckets(deltas: list[PnlDelta]) -> list[float]:
    buckets = [0.0] * 24
    for delta in deltas:
        hour = datetime.fromtimestamp(int(delta.timestamp), tz=timezone.utc).hour
        buckets[hour] += float(delta.delta_pnl_usdc)
    return [round(v, 10) for v in buckets]


def _compute_market_scatter_point(
    market: PolymarketMarket,
    all_trades: list[TradeRecord],
    market_report: MarketReport,
) -> MarketScatterPoint | None:
    token_ids = {market.up_token_id, market.down_token_id}
    buy_notional = 0.0
    buy_qty = 0.0
    for trade in all_trades:
        if trade.side != "BUY":
            continue
        if trade.asset not in token_ids:
            continue
        buy_notional += float(trade.price) * float(trade.size)
        buy_qty += float(trade.size)
    if buy_notional <= 0.0 or buy_qty <= 0.0:
        return None
    avg_entry = buy_notional / buy_qty
    pnl = float(market_report.realized_pnl_usdc)
    roc = (pnl / buy_notional) * 100.0 if buy_notional > 1e-12 else 0.0
    return MarketScatterPoint(
        market_slug=market.slug,
        avg_entry_price=round(avg_entry, 6),
        realized_pnl_usdc=round(pnl, 10),
        return_on_cost_pct=round(roc, 4),
        buy_notional_usdc=round(buy_notional, 10),
    )


def _cumulative_at(by_ts: dict[int, float], ts: int) -> float:
    cumulative = 0.0
    for key in sorted(by_ts.keys()):
        if key > ts:
            break
        cumulative += by_ts[key]
    return cumulative


def _market_order_key(slug: str) -> tuple[int, str]:
    try:
        return int(str(slug).rsplit("-", 1)[-1]), slug
    except Exception:  # noqa: BLE001
        return 10**18, slug


def _has_market_trade_activity(market_report: MarketReport) -> bool:
    return any(token.trade_count > 0 for token in market_report.tokens)


def _chunk_specs_by_timestamp(
    specs: list[MarketSlugSpec], timestamps_per_chunk: int
) -> list[list[MarketSlugSpec]]:
    if not specs:
        return []
    chunk_size = max(1, int(timestamps_per_chunk))

    ts_to_specs: dict[int, list[MarketSlugSpec]] = defaultdict(list)
    ts_order: list[int] = []
    for spec in specs:
        if spec.timestamp not in ts_to_specs:
            ts_order.append(spec.timestamp)
        ts_to_specs[spec.timestamp].append(spec)

    chunks: list[list[MarketSlugSpec]] = []
    for start in range(0, len(ts_order), chunk_size):
        ts_slice = ts_order[start : start + chunk_size]
        chunk_specs: list[MarketSlugSpec] = []
        for ts in ts_slice:
            chunk_specs.extend(ts_to_specs[ts])
        chunks.append(chunk_specs)
    return chunks


def _result_to_cache_payload(result: _MarketProcessResult) -> dict:
    payload = {
        "market_slug": result.market_slug,
        "market_report": result.market_report.model_dump(),
        "market_report_no_fee": result.market_report_no_fee.model_dump(),
        "deltas": [_delta_to_dict(d) for d in result.deltas],
        "deltas_no_fee": [_delta_to_dict(d) for d in result.deltas_no_fee],
        "warnings": [w.model_dump() for w in result.warnings],
    }
    if result.scatter_point is not None:
        payload["scatter_point"] = result.scatter_point.model_dump()
    return payload


def _result_from_cache_payload(slug: str, payload: dict) -> _MarketProcessResult | None:
    try:
        market_report = MarketReport.model_validate(payload["market_report"])
        market_report_no_fee = MarketReport.model_validate(payload["market_report_no_fee"])
        deltas = [_delta_from_dict(d) for d in payload.get("deltas", [])]
        deltas_no_fee = [_delta_from_dict(d) for d in payload.get("deltas_no_fee", [])]
        warnings = [WarningItem.model_validate(w) for w in payload.get("warnings", [])]
        scatter_raw = payload.get("scatter_point")
        scatter_point = (
            MarketScatterPoint.model_validate(scatter_raw) if scatter_raw is not None else None
        )
        return _MarketProcessResult(
            market_slug=slug,
            market_report=market_report,
            market_report_no_fee=market_report_no_fee,
            deltas=deltas,
            deltas_no_fee=deltas_no_fee,
            warnings=warnings,
            scatter_point=scatter_point,
        )
    except Exception:  # noqa: BLE001
        return None


def _delta_to_dict(delta: PnlDelta) -> dict:
    return {
        "timestamp": int(delta.timestamp),
        "market_slug": str(delta.market_slug),
        "token_id": str(delta.token_id),
        "delta_pnl_usdc": float(delta.delta_pnl_usdc),
    }


def _delta_from_dict(payload: dict) -> PnlDelta:
    return PnlDelta(
        timestamp=int(payload["timestamp"]),
        market_slug=str(payload["market_slug"]),
        token_id=str(payload["token_id"]),
        delta_pnl_usdc=float(payload["delta_pnl_usdc"]),
    )


def _is_market_result_cache_eligible(slug: str, now_ts: int, recent_window_sec: int) -> bool:
    market_ts = _market_order_key(slug)[0]
    if market_ts >= 10**18:
        return False
    return (now_ts - market_ts) > recent_window_sec
