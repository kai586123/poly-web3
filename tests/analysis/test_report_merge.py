"""Tests for merging per-wallet AnalysisReport instances into an aggregate dashboard report."""

from analysis_poly.models import (
    AnalysisReport,
    AnalysisRequest,
    CurvePoint,
    PnlTurnoverPoint,
    SessionAnalytics,
    SummaryStats,
    TradeSession,
    WarningItem,
)
from analysis_poly.report_merge import merge_analysis_reports

ADDR_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ADDR_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _shared_multi_req() -> AnalysisRequest:
    return AnalysisRequest(
        addresses=[ADDR_A, ADDR_B],
        start_ts=1000,
        end_ts=2000,
        symbols=["btc"],
        intervals=[5],
    )


def _single_req(addr: str) -> AnalysisRequest:
    return AnalysisRequest(
        address=addr,
        start_ts=1000,
        end_ts=2000,
        symbols=["btc"],
        intervals=[5],
    )


def _minimal_report(
    req: AnalysisRequest,
    *,
    total_curve: list[CurvePoint] | None = None,
    total_pnl_turnover_curve: list[PnlTurnoverPoint] | None = None,
    summary: SummaryStats | None = None,
    hourly: list[float] | None = None,
    warnings: list[WarningItem] | None = None,
    is_partial: bool = False,
    session_analytics: SessionAnalytics | None = None,
    source_addresses: list[str] | None = None,
) -> AnalysisReport:
    return AnalysisReport(
        request=req,
        source_addresses=list(source_addresses or [req.address or ""]),
        summary=summary
        or SummaryStats(
            total_realized_pnl_usdc=0.0,
            total_taker_fee_usdc=0.0,
            total_maker_reward_usdc=0.0,
            markets_total=3,
            markets_processed=0,
        ),
        markets=[],
        total_curve=total_curve or [],
        market_curves={},
        warnings=warnings or [],
        is_partial=is_partial,
        total_pnl_turnover_curve=total_pnl_turnover_curve or [],
        hourly_realized_pnl_usdc=hourly or ([0.0] * 24),
        session_analytics=session_analytics or SessionAnalytics(),
    )


def test_merge_single_report_updates_request_and_strips_per_wallet():
    shared = _shared_multi_req()
    inner = _minimal_report(
        _single_req(ADDR_A),
        total_curve=[
            CurvePoint(timestamp=1000, delta_realized_pnl_usdc=1.0, cumulative_realized_pnl_usdc=1.0),
        ],
        summary=SummaryStats(
            total_realized_pnl_usdc=5.0,
            total_taker_fee_usdc=1.0,
            total_maker_reward_usdc=0.5,
            markets_total=3,
            markets_processed=2,
        ),
        source_addresses=[ADDR_A],
    )
    out = merge_analysis_reports([inner], shared, [ADDR_A])
    assert out.request is shared
    assert out.source_addresses == [ADDR_A]
    assert out.per_wallet is None
    assert out.wallet_total_curves == {}
    assert out.wallet_total_curves_no_fee == {}
    assert len(out.total_curve) == 1


def test_merge_two_wallets_sums_deltas_at_shared_timestamps():
    shared = _shared_multi_req()
    r1 = _minimal_report(
        _single_req(ADDR_A),
        total_curve=[
            CurvePoint(timestamp=1000, delta_realized_pnl_usdc=1.0, cumulative_realized_pnl_usdc=1.0),
            CurvePoint(timestamp=1100, delta_realized_pnl_usdc=2.0, cumulative_realized_pnl_usdc=3.0),
        ],
        summary=SummaryStats(
            total_realized_pnl_usdc=10.0,
            total_taker_fee_usdc=1.0,
            total_maker_reward_usdc=2.0,
            markets_total=3,
            markets_processed=1,
        ),
        hourly=[1.0] + [0.0] * 23,
    )
    r2 = _minimal_report(
        _single_req(ADDR_B),
        total_curve=[
            CurvePoint(timestamp=1050, delta_realized_pnl_usdc=3.0, cumulative_realized_pnl_usdc=3.0),
            CurvePoint(timestamp=1100, delta_realized_pnl_usdc=1.0, cumulative_realized_pnl_usdc=4.0),
        ],
        summary=SummaryStats(
            total_realized_pnl_usdc=20.0,
            total_taker_fee_usdc=3.0,
            total_maker_reward_usdc=4.0,
            markets_total=3,
            markets_processed=1,
        ),
        hourly=[2.0] + [0.0] * 23,
    )
    merged = merge_analysis_reports([r1, r2], shared, [ADDR_A, ADDR_B])
    cum = [(p.timestamp, round(p.cumulative_realized_pnl_usdc, 6)) for p in merged.total_curve]
    assert cum == [(1000, 1.0), (1050, 4.0), (1100, 7.0)]
    assert merged.summary.total_realized_pnl_usdc == 30.0
    assert merged.summary.total_taker_fee_usdc == 4.0
    assert merged.summary.total_maker_reward_usdc == 6.0
    assert merged.hourly_realized_pnl_usdc[0] == 3.0
    assert set(merged.wallet_total_curves.keys()) == {ADDR_A, ADDR_B}
    assert merged.wallet_total_curves[ADDR_A][-1].cumulative_realized_pnl_usdc == 3.0
    assert merged.wallet_total_curves[ADDR_B][-1].cumulative_realized_pnl_usdc == 4.0


def test_merge_turnover_curve_prepends_start_ts_anchor():
    shared = _shared_multi_req()
    r1 = _minimal_report(
        _single_req(ADDR_A),
        total_pnl_turnover_curve=[
            PnlTurnoverPoint(
                timestamp=1001,
                cumulative_turnover_usdc=10.0,
                cumulative_realized_pnl_usdc=1.0,
                cumulative_realized_pnl_usdc_no_fee=1.1,
            ),
        ],
    )
    r2 = _minimal_report(
        _single_req(ADDR_B),
        total_pnl_turnover_curve=[
            PnlTurnoverPoint(
                timestamp=1002,
                cumulative_turnover_usdc=5.0,
                cumulative_realized_pnl_usdc=2.0,
                cumulative_realized_pnl_usdc_no_fee=2.2,
            ),
        ],
    )
    merged = merge_analysis_reports([r1, r2], shared, [ADDR_A, ADDR_B])
    assert merged.total_pnl_turnover_curve[0].timestamp == shared.start_ts
    assert merged.total_pnl_turnover_curve[0].cumulative_turnover_usdc == 0.0
    assert merged.total_pnl_turnover_curve[-1].timestamp == 1002


def test_merge_concatenates_warnings_with_source_address():
    shared = _shared_multi_req()
    r1 = _minimal_report(
        _single_req(ADDR_A),
        warnings=[WarningItem(code="W1", message="a")],
    )
    r2 = _minimal_report(
        _single_req(ADDR_B),
        warnings=[WarningItem(code="W2", message="b", source_address=None)],
    )
    merged = merge_analysis_reports([r1, r2], shared, [ADDR_A, ADDR_B])
    assert len(merged.warnings) == 2
    assert merged.warnings[0].source_address == ADDR_A
    assert merged.warnings[1].source_address == ADDR_B


def test_merge_tags_trade_sessions_with_source_and_stacks():
    shared = _shared_multi_req()
    s1 = TradeSession(
        market_slug="m1",
        start_timestamp=1,
        end_timestamp=2,
        is_chart_eligible=False,
        exclusion_reason="no_trade_entry",
    )
    s2 = TradeSession(
        market_slug="m2",
        start_timestamp=3,
        end_timestamp=4,
        is_chart_eligible=False,
        exclusion_reason="no_trade_entry",
    )
    r1 = _minimal_report(
        _single_req(ADDR_A),
        session_analytics=SessionAnalytics(trade_sessions=[s1]),
    )
    r2 = _minimal_report(
        _single_req(ADDR_B),
        session_analytics=SessionAnalytics(trade_sessions=[s2]),
    )
    merged = merge_analysis_reports([r1, r2], shared, [ADDR_A, ADDR_B])
    tags = {s.source_address for s in merged.session_analytics.trade_sessions}
    assert tags == {ADDR_A, ADDR_B}
    assert merged.session_analytics.diagnostics.total_detected_sessions == 2


def test_merge_is_partial_if_any_wallet_partial():
    shared = _shared_multi_req()
    r1 = _minimal_report(_single_req(ADDR_A), is_partial=False)
    r2 = _minimal_report(_single_req(ADDR_B), is_partial=True)
    merged = merge_analysis_reports([r1, r2], shared, [ADDR_A, ADDR_B])
    assert merged.is_partial is True
