"""Merge multiple single-wallet AnalysisReport instances into one aggregate dashboard report."""

from __future__ import annotations

from collections import defaultdict
from .models import (
    AnalysisReport,
    AnalysisRequest,
    CurvePoint,
    MarketReport,
    PnlTurnoverPoint,
    SummaryStats,
    TokenReport,
    TradeSession,
    WarningItem,
)


def _merge_curve(curves: list[list[CurvePoint]]) -> list[CurvePoint]:
    by_ts: dict[int, float] = defaultdict(float)
    for curve in curves:
        for p in curve:
            by_ts[p.timestamp] += float(p.delta_realized_pnl_usdc)
    cumulative = 0.0
    out: list[CurvePoint] = []
    for ts in sorted(by_ts.keys()):
        d = by_ts[ts]
        cumulative += d
        out.append(
            CurvePoint(
                timestamp=int(ts),
                delta_realized_pnl_usdc=round(d, 10),
                cumulative_realized_pnl_usdc=round(cumulative, 10),
            )
        )
    return out


def _merge_curve_dict(curves_per_report: list[dict[str, list[CurvePoint]]]) -> dict[str, list[CurvePoint]]:
    all_keys: set[str] = set()
    for d in curves_per_report:
        all_keys.update(d.keys())
    merged: dict[str, list[CurvePoint]] = {}
    for key in sorted(all_keys):
        curves = [d.get(key, []) for d in curves_per_report]
        if not any(curves):
            continue
        merged[key] = _merge_curve(curves)
    return merged


def _merge_pnl_turnover_curves(curves: list[list[PnlTurnoverPoint]]) -> list[PnlTurnoverPoint]:
    """Sum step deltas in turnover and both PnL legs, rebuild cumulatives."""
    d_turn: dict[int, float] = defaultdict(float)
    d_pnl: dict[int, float] = defaultdict(float)
    d_pnl_nf: dict[int, float] = defaultdict(float)
    for series in curves:
        prev_t = prev_p = prev_nf = 0.0
        for p in sorted(series, key=lambda x: x.timestamp):
            ts = p.timestamp
            d_turn[ts] += float(p.cumulative_turnover_usdc) - prev_t
            d_pnl[ts] += float(p.cumulative_realized_pnl_usdc) - prev_p
            d_pnl_nf[ts] += float(p.cumulative_realized_pnl_usdc_no_fee) - prev_nf
            prev_t = float(p.cumulative_turnover_usdc)
            prev_p = float(p.cumulative_realized_pnl_usdc)
            prev_nf = float(p.cumulative_realized_pnl_usdc_no_fee)

    all_ts = sorted(set(d_turn) | set(d_pnl) | set(d_pnl_nf))
    cum_t = cum_p = cum_nf = 0.0
    out: list[PnlTurnoverPoint] = []
    for ts in all_ts:
        cum_t += d_turn.get(ts, 0.0)
        cum_p += d_pnl.get(ts, 0.0)
        cum_nf += d_pnl_nf.get(ts, 0.0)
        out.append(
            PnlTurnoverPoint(
                timestamp=int(ts),
                cumulative_turnover_usdc=round(cum_t, 10),
                cumulative_realized_pnl_usdc=round(cum_p, 10),
                cumulative_realized_pnl_usdc_no_fee=round(cum_nf, 10),
            )
        )
    return out


def _merge_tokens(token_lists: list[list[TokenReport]]) -> list[TokenReport]:
    by_id: dict[str, list[TokenReport]] = defaultdict(list)
    for tokens in token_lists:
        for t in tokens:
            by_id[t.token_id].append(t)
    merged: list[TokenReport] = []
    for token_id in sorted(by_id.keys()):
        lst = by_id[token_id]
        base = lst[0]
        merged.append(
            TokenReport(
                token_id=base.token_id,
                side=base.side,
                outcome=base.outcome,
                realized_pnl_usdc=round(sum(t.realized_pnl_usdc for t in lst), 10),
                taker_fee_usdc=round(sum(t.taker_fee_usdc for t in lst), 10),
                maker_reward_usdc=round(sum(t.maker_reward_usdc for t in lst), 10),
                buy_qty=round(sum(t.buy_qty for t in lst), 10),
                sell_qty=round(sum(t.sell_qty for t in lst), 10),
                split_qty=round(sum(t.split_qty for t in lst), 10),
                redeem_qty=round(sum(t.redeem_qty for t in lst), 10),
                ending_position_qty=round(sum(t.ending_position_qty for t in lst), 10),
                trade_count=int(sum(t.trade_count for t in lst)),
            )
        )
    return merged


def _merge_markets(reports: list[AnalysisReport]) -> list[MarketReport]:
    by_slug: dict[str, list[MarketReport]] = defaultdict(list)
    for r in reports:
        for m in r.markets:
            by_slug[m.market_slug].append(m)
    out: list[MarketReport] = []
    for slug in sorted(by_slug.keys()):
        lst = by_slug[slug]
        first = lst[0]
        out.append(
            MarketReport(
                market_slug=slug,
                condition_id=first.condition_id,
                up_token_id=first.up_token_id,
                down_token_id=first.down_token_id,
                yes_outcome_label=first.yes_outcome_label,
                no_outcome_label=first.no_outcome_label,
                realized_pnl_usdc=round(sum(m.realized_pnl_usdc for m in lst), 10),
                taker_fee_usdc=round(sum(m.taker_fee_usdc for m in lst), 10),
                maker_reward_usdc=round(sum(m.maker_reward_usdc for m in lst), 10),
                ending_position_up=round(sum(m.ending_position_up for m in lst), 10),
                ending_position_down=round(sum(m.ending_position_down for m in lst), 10),
                tokens=_merge_tokens([m.tokens for m in lst]),
            )
        )
    return out


def _merge_summary(reports: list[AnalysisReport], markets_total: int) -> SummaryStats:
    return SummaryStats(
        total_realized_pnl_usdc=round(sum(r.summary.total_realized_pnl_usdc for r in reports), 10),
        total_taker_fee_usdc=round(sum(r.summary.total_taker_fee_usdc for r in reports), 10),
        total_maker_reward_usdc=round(sum(r.summary.total_maker_reward_usdc for r in reports), 10),
        markets_total=markets_total,
        markets_processed=len(_merge_markets(reports)),
    )


def _merge_hourly(reports: list[AnalysisReport]) -> list[float]:
    acc = [0.0] * 24
    for r in reports:
        for i, v in enumerate(r.hourly_realized_pnl_usdc):
            if i < 24:
                acc[i] += float(v)
    return [round(v, 10) for v in acc]


def _tag_sessions(sessions: list[TradeSession], source_address: str) -> list[TradeSession]:
    return [s.model_copy(update={"source_address": source_address}) for s in sessions]


def merge_analysis_reports(
    reports: list[AnalysisReport],
    shared_req: AnalysisRequest,
    source_addresses: list[str],
) -> AnalysisReport:
    if not reports:
        raise ValueError("reports must be non-empty")
    if len(reports) != len(source_addresses):
        raise ValueError("reports and source_addresses length mismatch")
    if len(reports) == 1:
        return reports[0].model_copy(
            update={
                "request": shared_req,
                "source_addresses": list(source_addresses),
                "per_wallet": None,
                "wallet_total_curves": {},
                "wallet_total_curves_no_fee": {},
            }
        )

    markets_total = reports[0].summary.markets_total
    merged_markets = _merge_markets(reports)

    all_sessions: list[TradeSession] = []
    all_warnings: list[WarningItem] = []

    for r, addr in zip(reports, source_addresses, strict=True):
        all_sessions.extend(_tag_sessions(r.session_analytics.trade_sessions, addr))
        all_warnings.extend(
            w.model_copy(update={"source_address": w.source_address or addr}) for w in r.warnings
        )

    # Rebuild session analytics from stacked sessions (correct buckets across wallets).
    from .analyzer import (  # noqa: PLC0415 — runtime import; avoids import cycle at module load
        _build_session_analytics,
        _build_session_analytics_by_side,
        _build_session_diagnostics_from_sessions,
    )

    combined_diag = _build_session_diagnostics_from_sessions(all_sessions)
    session_analytics = _build_session_analytics(all_sessions, combined_diag)
    session_analytics_by_side = _build_session_analytics_by_side(all_sessions)

    is_partial = any(r.is_partial for r in reports)

    tt_curve = _merge_pnl_turnover_curves([r.total_pnl_turnover_curve for r in reports])
    if tt_curve and int(tt_curve[0].timestamp) > int(shared_req.start_ts):
        tt_curve = [
            PnlTurnoverPoint(
                timestamp=int(shared_req.start_ts),
                cumulative_turnover_usdc=0.0,
                cumulative_realized_pnl_usdc=0.0,
                cumulative_realized_pnl_usdc_no_fee=0.0,
            ),
            *tt_curve,
        ]

    wallet_total_curves = {addr: list(r.total_curve) for r, addr in zip(reports, source_addresses, strict=True)}
    wallet_total_curves_no_fee = {
        addr: list(r.total_curve_no_fee) for r, addr in zip(reports, source_addresses, strict=True)
    }

    return AnalysisReport(
        request=shared_req,
        source_addresses=list(source_addresses),
        summary=_merge_summary(reports, markets_total),
        markets=merged_markets,
        total_curve=_merge_curve([r.total_curve for r in reports]),
        market_curves=_merge_curve_dict([r.market_curves for r in reports]),
        side_curves=_merge_curve_dict([r.side_curves for r in reports]),
        total_curve_no_fee=_merge_curve([r.total_curve_no_fee for r in reports]),
        market_curves_no_fee=_merge_curve_dict([r.market_curves_no_fee for r in reports]),
        side_curves_no_fee=_merge_curve_dict([r.side_curves_no_fee for r in reports]),
        total_pnl_turnover_curve=tt_curve,
        warnings=all_warnings,
        is_partial=is_partial,
        artifacts={},
        hourly_realized_pnl_usdc=_merge_hourly(reports),
        market_scatter=[],
        session_analytics=session_analytics,
        session_analytics_by_side=session_analytics_by_side,
        wallet_total_curves=wallet_total_curves,
        wallet_total_curves_no_fee=wallet_total_curves_no_fee,
        per_wallet=None,
    )
