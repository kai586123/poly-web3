from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from datetime import datetime, timezone

from loguru import logger

from .market_cache import MarketMetadataCache
from .models import (
    AnalysisReport,
    AnalysisRequest,
    CurvePoint,
    MarketReport,
    MarketScatterPoint,
    PolymarketMarket,
    SessionAnalytics,
    SessionAnalyticsDiagnostics,
    SessionOpenHourBucket,
    SessionOpenPriceBucket,
    SessionPeakNotionalBucket,
    SummaryStats,
    TradeSession,
    TradeRecord,
    WarningItem,
)
from .polymarket_client import PolymarketApiClient
from .raw_api_cache import RawPolymarketDataCache
from .profit_engine import PnlDelta, ProfitEngine, build_curve
from .slugs import MarketSlugSpec, generate_market_slug_specs

MARKET_FETCH_CONCURRENCY_DEFAULT = 10
MARKET_TIMESTAMP_CHUNK_SIZE_DEFAULT = 20
MARKET_RESULT_CACHE_RECENT_WINDOW_SEC = 30 * 60
MARKET_RESULT_CACHE_SCHEMA_VERSION = 4
DEFAULT_FALLBACK_FEE_RATE_BPS = 72.0
EMIT_LIVE_CURVE_POINTS = False
SESSION_PRICE_BIN_WIDTH = 0.01
SESSION_PRICE_BIN_COUNT = 100
SESSION_PEAK_NOTIONAL_BIN_WIDTH = 10.0
SESSION_PEAK_NOTIONAL_BIN_COUNT = 200
MARKET_CATEGORY_MAKER_REWARD_RATIO = {
    "crypto": 0.20,
    "sports": 0.25,
    "finance": 0.25,
    "politics": 0.25,
    "economics": 0.25,
    "culture": 0.25,
    "weather": 0.25,
    "other": 0.25,
    "general": 0.25,
    "mentions": 0.25,
    "tech": 0.25,
    "geopolitics": 0.0,
}
MARKET_CATEGORY_TAKER_FEE_RATE_BPS = {
    "crypto": 72.0,
    "sports": 30.0,
    "finance": 40.0,
    "politics": 40.0,
    "economics": 50.0,
    "culture": 50.0,
    "weather": 50.0,
    "other": 50.0,
    "general": 50.0,
    "mentions": 40.0,
    "tech": 40.0,
    "geopolitics": 0.0,
}


@dataclass
class _MarketProcessResult:
    market_slug: str
    market_report: MarketReport
    market_report_no_fee: MarketReport
    deltas: list[PnlDelta]
    deltas_no_fee: list[PnlDelta]
    warnings: list[WarningItem]
    trade_sessions: list[TradeSession]
    session_diagnostics: SessionAnalyticsDiagnostics
    side_trade_sessions: dict[str, list[TradeSession]]
    side_session_diagnostics: dict[str, SessionAnalyticsDiagnostics]
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

        disable_raw_cache = os.getenv("ANALYSIS_POLY_DISABLE_RAW_API_CACHE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        raw_api_cache = None if disable_raw_cache else RawPolymarketDataCache()
        client = PolymarketApiClient(timeout_sec=req.request_timeout_sec, raw_data_cache=raw_api_cache)
        # Modeled maker rebate is off by default (not from API). Set ANALYSIS_POLY_ENABLE_MAKER_REBATE=1 to enable.
        # ANALYSIS_POLY_DISABLE_MAKER_REBATE=1 still forces off when set (legacy).
        enable_maker_rebate = os.getenv("ANALYSIS_POLY_ENABLE_MAKER_REBATE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        legacy_disable_maker_rebate = os.getenv("ANALYSIS_POLY_DISABLE_MAKER_REBATE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        apply_maker_rebate_model = enable_maker_rebate and not legacy_disable_maker_rebate
        engine = ProfitEngine(
            fee_rate_bps=req.fee_rate_bps,
            maker_reward_ratio=req.maker_reward_ratio,
            missing_cost_warn_qty=req.missing_cost_warn_qty,
            apply_maker_reward=apply_maker_rebate_model,
        )
        engine_no_fee = ProfitEngine(
            fee_rate_bps=req.fee_rate_bps,
            maker_reward_ratio=req.maker_reward_ratio,
            missing_cost_warn_qty=req.missing_cost_warn_qty,
            charge_taker_fee=False,
            apply_maker_reward=False,
        )

        all_warnings: list[WarningItem] = []
        market_reports: list[MarketReport] = []
        market_scatter_points: list[MarketScatterPoint] = []
        trade_sessions: list[TradeSession] = []
        session_diagnostics = SessionAnalyticsDiagnostics()
        side_trade_sessions: dict[str, list[TradeSession]] = {"YES": [], "NO": []}
        side_session_diagnostics: dict[str, SessionAnalyticsDiagnostics] = {
            "YES": SessionAnalyticsDiagnostics(),
            "NO": SessionAnalyticsDiagnostics(),
        }
        total_deltas: list[PnlDelta] = []
        total_deltas_no_fee: list[PnlDelta] = []
        market_deltas: dict[str, list[PnlDelta]] = defaultdict(list)
        market_deltas_no_fee: dict[str, list[PnlDelta]] = defaultdict(list)
        side_deltas: dict[str, list[PnlDelta]] = defaultdict(list)
        side_deltas_no_fee: dict[str, list[PnlDelta]] = defaultdict(list)

        total_running_pnl = 0.0
        total_running_pnl_no_fee = 0.0
        market_running_pnl: dict[str, float] = defaultdict(float)
        market_running_pnl_no_fee: dict[str, float] = defaultdict(float)
        fee_rate_bps_cache: dict[str, float] = {}

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
                                req=req,
                                market=market,
                                fee_rate_bps_cache=fee_rate_bps_cache,
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
                            side_by_token_id = {
                                result.market_report.up_token_id: "YES",
                                result.market_report.down_token_id: "NO",
                            }
                            if result.deltas:
                                market_deltas[result.market_slug].extend(result.deltas)
                                for delta in result.deltas:
                                    side = side_by_token_id.get(delta.token_id)
                                    if side:
                                        side_deltas[side].append(delta)
                            if result.deltas_no_fee:
                                market_deltas_no_fee[result.market_slug].extend(result.deltas_no_fee)
                                for delta in result.deltas_no_fee:
                                    side = side_by_token_id.get(delta.token_id)
                                    if side:
                                        side_deltas_no_fee[side].append(delta)
                        else:
                            logger.debug("skip market without trades in output slug={}", result.market_slug)

                        if result.trade_sessions:
                            trade_sessions.extend(result.trade_sessions)
                        for side in ("YES", "NO"):
                            side_trade_sessions[side].extend(result.side_trade_sessions.get(side, []))
                        session_diagnostics.total_detected_sessions += result.session_diagnostics.total_detected_sessions
                        session_diagnostics.closed_sessions += result.session_diagnostics.closed_sessions
                        session_diagnostics.chart_eligible_sessions += result.session_diagnostics.chart_eligible_sessions
                        session_diagnostics.excluded_open_session_count += (
                            result.session_diagnostics.excluded_open_session_count
                        )
                        session_diagnostics.excluded_no_trade_entry_count += (
                            result.session_diagnostics.excluded_no_trade_entry_count
                        )
                        session_diagnostics.excluded_zero_open_notional_count += (
                            result.session_diagnostics.excluded_zero_open_notional_count
                        )
                        session_diagnostics.excluded_warning_session_count += (
                            result.session_diagnostics.excluded_warning_session_count
                        )
                        for side in ("YES", "NO"):
                            side_diag = result.side_session_diagnostics.get(side, SessionAnalyticsDiagnostics())
                            side_session_diagnostics[side].total_detected_sessions += side_diag.total_detected_sessions
                            side_session_diagnostics[side].closed_sessions += side_diag.closed_sessions
                            side_session_diagnostics[side].chart_eligible_sessions += side_diag.chart_eligible_sessions
                            side_session_diagnostics[side].excluded_open_session_count += (
                                side_diag.excluded_open_session_count
                            )
                            side_session_diagnostics[side].excluded_no_trade_entry_count += (
                                side_diag.excluded_no_trade_entry_count
                            )
                            side_session_diagnostics[side].excluded_zero_open_notional_count += (
                                side_diag.excluded_zero_open_notional_count
                            )
                            side_session_diagnostics[side].excluded_warning_session_count += (
                                side_diag.excluded_warning_session_count
                            )

                        for warning in result.warnings:
                            all_warnings.append(warning)
                            await hooks.on_warning(warning)

                        if EMIT_LIVE_CURVE_POINTS:
                            for delta in result.deltas:
                                total_running_pnl += delta.delta_pnl_usdc
                                market_running_pnl[delta.market_slug] += delta.delta_pnl_usdc
                                await hooks.on_total_point(
                                    delta.timestamp,
                                    delta.delta_pnl_usdc,
                                    total_running_pnl,
                                )
                                await hooks.on_market_point(
                                    delta.market_slug,
                                    delta.timestamp,
                                    delta.delta_pnl_usdc,
                                    market_running_pnl[delta.market_slug],
                                )

                            for delta in result.deltas_no_fee:
                                total_running_pnl_no_fee += delta.delta_pnl_usdc
                                market_running_pnl_no_fee[delta.market_slug] += delta.delta_pnl_usdc
                                await hooks.on_total_point_no_fee(
                                    delta.timestamp,
                                    delta.delta_pnl_usdc,
                                    total_running_pnl_no_fee,
                                )
                                await hooks.on_market_point_no_fee(
                                    delta.market_slug,
                                    delta.timestamp,
                                    delta.delta_pnl_usdc,
                                    market_running_pnl_no_fee[delta.market_slug],
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

            side_curves: dict[str, list[CurvePoint]] = {}
            for side, deltas in side_deltas.items():
                if not deltas:
                    continue
                side_curves[side] = [
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

            side_curves_no_fee: dict[str, list[CurvePoint]] = {}
            for side, deltas in side_deltas_no_fee.items():
                if not deltas:
                    continue
                side_curves_no_fee[side] = [
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
            session_analytics = _build_session_analytics(trade_sessions, session_diagnostics)
            session_analytics_by_side = {
                side: _build_session_analytics(side_trade_sessions[side], side_session_diagnostics[side])
                for side in ("YES", "NO")
            }

            report = AnalysisReport(
                request=req,
                summary=summary,
                markets=sorted(market_reports, key=lambda x: x.market_slug),
                total_curve=total_curve,
                market_curves=market_curves,
                side_curves=side_curves,
                total_curve_no_fee=total_curve_no_fee,
                market_curves_no_fee=market_curves_no_fee,
                side_curves_no_fee=side_curves_no_fee,
                warnings=all_warnings,
                is_partial=stop_event.is_set() and len(market_reports) < total_markets,
                hourly_realized_pnl_usdc=_build_hourly_pnl_buckets(total_deltas),
                market_scatter=sorted(market_scatter_points, key=lambda x: x.market_slug),
                session_analytics=session_analytics,
                session_analytics_by_side=session_analytics_by_side,
            )

            return report
        finally:
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
        req: AnalysisRequest,
        market,
        fee_rate_bps_cache: dict[str, float],
    ) -> _MarketProcessResult:
        taker_trades, all_trades, split_acts, redeem_acts = await asyncio.gather(
            client.get_trades(req.address, market.condition_id, True, req.page_limit),
            client.get_trades(req.address, market.condition_id, False, req.page_limit),
            client.get_activity(req.address, market.condition_id, "SPLIT", req.page_limit),
            client.get_activity(req.address, market.condition_id, "REDEEM", req.page_limit),
        )

        fee_rate_bps_by_token, fee_warnings = await self._resolve_market_fee_rate_bps_by_token(
            client=client,
            market=market,
            fallback_fee_rate_bps=req.fee_rate_bps,
            fee_rate_bps_cache=fee_rate_bps_cache,
        )
        maker_reward_ratio = _maker_reward_ratio_for_market_category(market.category, default=req.maker_reward_ratio)

        replay = engine.analyze_market(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_acts,
            redeem_activities=redeem_acts,
            fee_rate_bps_by_token=fee_rate_bps_by_token,
            maker_reward_ratio_override=maker_reward_ratio,
        )
        market_report = replay.report
        deltas = replay.deltas
        warnings = [*replay.warnings, *fee_warnings]
        market_report_no_fee, deltas_no_fee, _ = engine_no_fee.process_market(
            market=market,
            taker_trades=taker_trades,
            all_trades=all_trades,
            split_activities=split_acts,
            redeem_activities=redeem_acts,
            fee_rate_bps_by_token=fee_rate_bps_by_token,
            maker_reward_ratio_override=maker_reward_ratio,
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
            trade_sessions=replay.trade_sessions,
            session_diagnostics=replay.session_diagnostics,
            side_trade_sessions=replay.side_trade_sessions,
            side_session_diagnostics=replay.side_session_diagnostics,
            scatter_point=scatter_point,
        )
        return result

    async def _resolve_market_fee_rate_bps_by_token(
        self,
        client: PolymarketApiClient,
        market: PolymarketMarket,
        fallback_fee_rate_bps: float,
        fee_rate_bps_cache: dict[str, float],
    ) -> tuple[dict[str, float], list[WarningItem]]:
        if market.fees_enabled is False:
            return {market.up_token_id: 0.0, market.down_token_id: 0.0}, []

        warnings: list[WarningItem] = []
        category_default_bps = _taker_fee_rate_bps_for_market_category(market.category)
        rates: dict[str, float] = {}
        for token_id in (market.up_token_id, market.down_token_id):
            if token_id in fee_rate_bps_cache:
                rates[token_id] = fee_rate_bps_cache[token_id]
                continue
            try:
                fetched = await client.get_fee_rate_bps(token_id)
            except Exception as exc:  # noqa: BLE001
                fetched = None
                warnings.append(
                    WarningItem(
                        market_slug=market.slug,
                        token_id=token_id,
                        code="FEE_RATE_FETCH_FAILED",
                        message=f"fee-rate lookup failed; fallback is used ({exc})",
                    )
                )
            # Fallback always uses current documented Crypto taker fee rate.
            fallback_rate_bps = DEFAULT_FALLBACK_FEE_RATE_BPS
            rate = fallback_rate_bps
            if fetched is not None:
                normalized = _normalize_fee_rate_bps(float(fetched), category_default_bps)
                rate = normalized
                if abs(normalized - float(fetched)) > 1e-9:
                    warnings.append(
                        WarningItem(
                            market_slug=market.slug,
                            token_id=token_id,
                            code="FEE_RATE_NORMALIZED",
                            message=(
                                f"fee-rate endpoint value {float(fetched)} normalized to {normalized}"
                            ),
                        )
                    )
            else:
                warnings.append(
                    WarningItem(
                        market_slug=market.slug,
                        token_id=token_id,
                        code="FEE_RATE_FALLBACK",
                        message=f"fee-rate endpoint unavailable; fallback fee_rate_bps={fallback_rate_bps}",
                    )
                )
            rates[token_id] = max(0.0, rate)
            fee_rate_bps_cache[token_id] = rates[token_id]
        return rates, warnings

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


def _maker_reward_ratio_for_market_category(category: str | None, default: float) -> float:
    key = str(category or "").strip().lower()
    if key in MARKET_CATEGORY_MAKER_REWARD_RATIO:
        return float(MARKET_CATEGORY_MAKER_REWARD_RATIO[key])
    return float(default)


def _taker_fee_rate_bps_for_market_category(category: str | None) -> float | None:
    key = str(category or "").strip().lower()
    if key in MARKET_CATEGORY_TAKER_FEE_RATE_BPS:
        return float(MARKET_CATEGORY_TAKER_FEE_RATE_BPS[key])
    return None


def _normalize_fee_rate_bps(raw_fee_rate_bps: float, category_default_bps: float | None) -> float:
    raw = max(0.0, float(raw_fee_rate_bps))
    if raw <= 1.0:
        # Some endpoints may return rate (e.g. 0.072) instead of bps-like integer (72).
        return raw * 1000.0
    if raw <= 200.0:
        return raw
    # Large values (e.g. 1000 from order payload examples) are not usable directly
    # in analyzer fee math; prefer documented category defaults when available.
    if category_default_bps is not None:
        return category_default_bps
    return DEFAULT_FALLBACK_FEE_RATE_BPS


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


def _build_session_analytics(
    sessions: list[TradeSession],
    diagnostics: SessionAnalyticsDiagnostics,
) -> SessionAnalytics:
    ordered_sessions = sorted(sessions, key=lambda s: (_market_order_key(s.market_slug), s.start_timestamp, s.end_timestamp))
    hour_acc = {
        hour: {
            "count": 0,
            "sum_pnl": 0.0,
            "sum_notional": 0.0,
            "sum_return": 0.0,
            "sum_win_score": 0.0,
        }
        for hour in range(24)
    }
    price_acc: dict[int, dict[str, float]] = defaultdict(
        lambda: {
            "count": 0,
            "sum_pnl": 0.0,
            "sum_notional": 0.0,
            "sum_return": 0.0,
            "sum_win_score": 0.0,
        }
    )
    peak_acc: dict[int, dict[str, float]] = defaultdict(
        lambda: {
            "count": 0,
            "sum_pnl": 0.0,
            "sum_notional": 0.0,
            "sum_return": 0.0,
            "sum_win_score": 0.0,
            "sum_peak": 0.0,
        }
    )

    for session in ordered_sessions:
        if (
            not session.is_chart_eligible
            or session.open_hour_utc is None
            or session.open_avg_price is None
            or session.return_on_open_notional_pct is None
        ):
            continue
        hour_stats = hour_acc[int(session.open_hour_utc)]
        hour_stats["count"] += 1
        hour_stats["sum_pnl"] += float(session.realized_pnl_usdc)
        hour_stats["sum_notional"] += float(session.open_notional_usdc)
        hour_stats["sum_return"] += float(session.return_on_open_notional_pct)
        hour_stats["sum_win_score"] += _session_win_score(session)

        price_stats = price_acc[_price_bucket_index(float(session.open_avg_price))]
        price_stats["count"] += 1
        price_stats["sum_pnl"] += float(session.realized_pnl_usdc)
        price_stats["sum_notional"] += float(session.open_notional_usdc)
        price_stats["sum_return"] += float(session.return_on_open_notional_pct)
        price_stats["sum_win_score"] += _session_win_score(session)

        peak_stats = peak_acc[_peak_notional_bucket_index(float(session.peak_position_notional_usdc))]
        peak_stats["count"] += 1
        peak_stats["sum_pnl"] += float(session.realized_pnl_usdc)
        peak_stats["sum_notional"] += float(session.open_notional_usdc)
        peak_stats["sum_return"] += float(session.return_on_open_notional_pct)
        peak_stats["sum_win_score"] += _session_win_score(session)
        peak_stats["sum_peak"] += float(session.peak_position_notional_usdc)

    hour_buckets = [
        SessionOpenHourBucket(
            hour_utc=hour,
            session_count=int(stats["count"]),
            weighted_return_on_open_notional_pct=round(
                (stats["sum_pnl"] / stats["sum_notional"]) * 100.0 if stats["sum_notional"] > 1e-12 else 0.0,
                6,
            ),
            average_return_on_open_notional_pct=round(
                stats["sum_return"] / stats["count"] if stats["count"] else 0.0,
                6,
            ),
            win_rate_pct=round(
                (stats["sum_win_score"] / stats["count"]) * 100.0 if stats["count"] else 0.0,
                6,
            ),
            sum_realized_pnl_usdc=round(stats["sum_pnl"], 10),
            sum_open_notional_usdc=round(stats["sum_notional"], 10),
        )
        for hour, stats in hour_acc.items()
    ]

    price_buckets = [
        SessionOpenPriceBucket(
            bin_index=idx,
            bin_start_price=round(idx * SESSION_PRICE_BIN_WIDTH, 2),
            bin_end_price=round(min(1.0, (idx + 1) * SESSION_PRICE_BIN_WIDTH), 2),
            session_count=int(stats["count"]),
            weighted_return_on_open_notional_pct=round(
                (stats["sum_pnl"] / stats["sum_notional"]) * 100.0 if stats["sum_notional"] > 1e-12 else 0.0,
                6,
            ),
            average_return_on_open_notional_pct=round(
                stats["sum_return"] / stats["count"] if stats["count"] else 0.0,
                6,
            ),
            win_rate_pct=round(
                (stats["sum_win_score"] / stats["count"]) * 100.0 if stats["count"] else 0.0,
                6,
            ),
            sum_realized_pnl_usdc=round(stats["sum_pnl"], 10),
            sum_open_notional_usdc=round(stats["sum_notional"], 10),
        )
        for idx, stats in sorted(price_acc.items())
    ]

    peak_buckets = [
        SessionPeakNotionalBucket(
            bin_index=idx,
            bin_start_usdc=round(idx * SESSION_PEAK_NOTIONAL_BIN_WIDTH, 2),
            bin_end_usdc=round((idx + 1) * SESSION_PEAK_NOTIONAL_BIN_WIDTH, 2),
            session_count=int(stats["count"]),
            weighted_return_on_open_notional_pct=round(
                (stats["sum_pnl"] / stats["sum_notional"]) * 100.0 if stats["sum_notional"] > 1e-12 else 0.0,
                6,
            ),
            average_return_on_open_notional_pct=round(
                stats["sum_return"] / stats["count"] if stats["count"] else 0.0,
                6,
            ),
            win_rate_pct=round(
                (stats["sum_win_score"] / stats["count"]) * 100.0 if stats["count"] else 0.0,
                6,
            ),
            sum_realized_pnl_usdc=round(stats["sum_pnl"], 10),
            sum_open_notional_usdc=round(stats["sum_notional"], 10),
            sum_peak_position_notional_usdc=round(stats["sum_peak"], 10),
        )
        for idx, stats in sorted(peak_acc.items())
    ]

    return SessionAnalytics(
        diagnostics=diagnostics,
        trade_sessions=ordered_sessions,
        open_hour_buckets=hour_buckets,
        open_price_buckets=price_buckets,
        open_peak_notional_buckets=peak_buckets,
    )


def _build_session_analytics_by_side(sessions: list[TradeSession]) -> dict[str, SessionAnalytics]:
    analytics_by_side: dict[str, SessionAnalytics] = {}
    for side in ("YES", "NO"):
        side_sessions = [session for session in sessions if session.entry_side == side]
        analytics_by_side[side] = _build_session_analytics(
            side_sessions,
            _build_session_diagnostics_from_sessions(side_sessions),
        )
    return analytics_by_side


def _build_session_diagnostics_from_sessions(sessions: list[TradeSession]) -> SessionAnalyticsDiagnostics:
    diagnostics = SessionAnalyticsDiagnostics(
        total_detected_sessions=len(sessions),
        closed_sessions=len(sessions),
    )
    for session in sessions:
        if session.is_chart_eligible:
            diagnostics.chart_eligible_sessions += 1
        elif session.exclusion_reason == "no_trade_entry":
            diagnostics.excluded_no_trade_entry_count += 1
        elif session.exclusion_reason == "zero_open_notional":
            diagnostics.excluded_zero_open_notional_count += 1
        else:
            diagnostics.excluded_warning_session_count += 1
    return diagnostics


def _price_bucket_index(price: float) -> int:
    clamped = max(0.0, min(float(price), 1.0))
    if clamped >= 1.0:
        return SESSION_PRICE_BIN_COUNT - 1
    return min(SESSION_PRICE_BIN_COUNT - 1, max(0, int(clamped / SESSION_PRICE_BIN_WIDTH)))


def _peak_notional_bucket_index(peak_usdc: float) -> int:
    p = max(0.0, float(peak_usdc))
    width = SESSION_PEAK_NOTIONAL_BIN_WIDTH
    raw = int(p // width)
    if raw >= SESSION_PEAK_NOTIONAL_BIN_COUNT:
        return SESSION_PEAK_NOTIONAL_BIN_COUNT - 1
    return min(SESSION_PEAK_NOTIONAL_BIN_COUNT - 1, max(0, raw))


def _session_win_score(session: TradeSession) -> float:
    return_pct = session.return_on_open_notional_pct
    if return_pct is not None and float(return_pct) > 1e-9:
        return 1.0
    if (
        session.open_avg_price is not None
        and session.close_avg_price is not None
        and abs(float(session.close_avg_price) - float(session.open_avg_price)) <= 1e-9
    ):
        return 0.5
    if return_pct is not None and float(return_pct) < -1e-9:
        return 0.0
    return 0.5


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
        "schema_version": MARKET_RESULT_CACHE_SCHEMA_VERSION,
        "market_slug": result.market_slug,
        "market_report": result.market_report.model_dump(),
        "market_report_no_fee": result.market_report_no_fee.model_dump(),
        "deltas": [_delta_to_dict(d) for d in result.deltas],
        "deltas_no_fee": [_delta_to_dict(d) for d in result.deltas_no_fee],
        "warnings": [w.model_dump() for w in result.warnings],
        "trade_sessions": [s.model_dump() for s in result.trade_sessions],
        "session_diagnostics": result.session_diagnostics.model_dump(),
        "side_trade_sessions": {
            side: [s.model_dump() for s in result.side_trade_sessions.get(side, [])] for side in ("YES", "NO")
        },
        "side_session_diagnostics": {
            side: result.side_session_diagnostics.get(side, SessionAnalyticsDiagnostics()).model_dump()
            for side in ("YES", "NO")
        },
    }
    if result.scatter_point is not None:
        payload["scatter_point"] = result.scatter_point.model_dump()
    return payload


def _result_from_cache_payload(slug: str, payload: dict) -> _MarketProcessResult | None:
    try:
        if int(payload.get("schema_version", 0)) != MARKET_RESULT_CACHE_SCHEMA_VERSION:
            return None
        market_report = MarketReport.model_validate(payload["market_report"])
        market_report_no_fee = MarketReport.model_validate(payload["market_report_no_fee"])
        deltas = [_delta_from_dict(d) for d in payload.get("deltas", [])]
        deltas_no_fee = [_delta_from_dict(d) for d in payload.get("deltas_no_fee", [])]
        warnings = [WarningItem.model_validate(w) for w in payload.get("warnings", [])]
        trade_sessions = [TradeSession.model_validate(s) for s in payload.get("trade_sessions", [])]
        session_diagnostics = SessionAnalyticsDiagnostics.model_validate(payload.get("session_diagnostics", {}))
        side_trade_sessions = {
            side: [TradeSession.model_validate(s) for s in payload.get("side_trade_sessions", {}).get(side, [])]
            for side in ("YES", "NO")
        }
        side_session_diagnostics = {
            side: SessionAnalyticsDiagnostics.model_validate(
                payload.get("side_session_diagnostics", {}).get(side, {})
            )
            for side in ("YES", "NO")
        }
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
            trade_sessions=trade_sessions,
            session_diagnostics=session_diagnostics,
            side_trade_sessions=side_trade_sessions,
            side_session_diagnostics=side_session_diagnostics,
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
