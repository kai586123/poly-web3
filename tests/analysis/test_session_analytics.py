from analysis_poly.analyzer import _build_session_analytics, _build_session_analytics_by_side
from analysis_poly.models import ActivityRecord, PolymarketMarket, SessionAnalyticsDiagnostics, TradeRecord, TradeSession
from analysis_poly.profit_engine import ProfitEngine


def _trade(tx: str, ts: int, side: str, asset: str, condition_id: str, size: float, price: float) -> TradeRecord:
    return TradeRecord.model_validate(
        {
            "transactionHash": tx,
            "timestamp": ts,
            "side": side,
            "asset": asset,
            "conditionId": condition_id,
            "size": size,
            "price": price,
        }
    )


def test_pair_detection_splits_buy_sell_buy_sell_into_two_pairs():
    market = PolymarketMarket(
        slug="btc-updown-5m-1000",
        condition_id="cond1",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
    )
    trades = [
        _trade("0x01", 1000, "BUY", "up_token", "cond1", 10, 0.4),
        _trade("0x02", 1010, "SELL", "up_token", "cond1", 5, 0.5),
        _trade("0x03", 1020, "BUY", "up_token", "cond1", 5, 0.6),
        _trade("0x04", 1030, "SELL", "up_token", "cond1", 10, 0.7),
    ]
    engine = ProfitEngine(fee_rate_bps=0, maker_reward_ratio=0, missing_cost_warn_qty=0.5)

    result = engine.analyze_market(
        market=market,
        taker_trades=trades,
        all_trades=trades,
        split_activities=[],
        redeem_activities=[],
    )

    assert len(result.trade_sessions) == 2
    first, second = result.trade_sessions
    assert first.entry_side == "YES"
    assert first.entry_outcome == "Up"
    assert first.start_timestamp == 1000
    assert first.end_timestamp == 1010
    assert round(first.open_avg_price, 6) == 0.4
    assert round(first.close_avg_price, 6) == 0.5
    assert round(first.open_qty, 10) == 5.0
    assert round(first.realized_pnl_usdc, 10) == 0.5
    assert round(first.return_on_open_notional_pct, 6) == 25.0

    assert second.entry_side == "YES"
    assert second.entry_outcome == "Up"
    assert second.start_timestamp == 1020
    assert second.end_timestamp == 1030
    assert round(second.open_avg_price, 6) == 0.6
    assert round(second.close_avg_price, 6) == 0.7
    assert round(second.open_qty, 10) == 5.0
    assert round(second.realized_pnl_usdc, 10) == 0.5
    assert round(second.return_on_open_notional_pct, 6) == 16.666667


def test_split_only_market_has_no_trade_pairs():
    market = PolymarketMarket(
        slug="eth-updown-15m-3000",
        condition_id="cond2",
        up_token_id="up",
        down_token_id="down",
        outcomes=["Up", "Down"],
        outcome_prices=[1, 0],
        closed=True,
    )
    split = ActivityRecord.model_validate(
        {
            "transactionHash": "0x10",
            "timestamp": 2000,
            "type": "SPLIT",
            "conditionId": "cond2",
            "size": 6,
            "usdcSize": 6,
        }
    )
    engine = ProfitEngine(fee_rate_bps=0, maker_reward_ratio=0, missing_cost_warn_qty=0.5)

    result = engine.analyze_market(
        market=market,
        taker_trades=[],
        all_trades=[],
        split_activities=[split],
        redeem_activities=[],
    )

    assert result.trade_sessions == []
    assert result.session_diagnostics.total_detected_sessions == 0
    assert result.session_diagnostics.chart_eligible_sessions == 0


def test_closed_market_settlement_closes_terminal_pair_at_settlement_price():
    market = PolymarketMarket(
        slug="btc-updown-5m-3000",
        condition_id="cond3",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[1, 0],
        closed=True,
    )
    trades = [_trade("0x11", 2990, "BUY", "up_token", "cond3", 10, 0.4)]
    engine = ProfitEngine(fee_rate_bps=0, maker_reward_ratio=0, missing_cost_warn_qty=0.5)

    result = engine.analyze_market(
        market=market,
        taker_trades=trades,
        all_trades=trades,
        split_activities=[],
        redeem_activities=[],
    )

    assert len(result.trade_sessions) == 1
    session = result.trade_sessions[0]
    assert session.end_timestamp == 3000
    assert round(session.close_avg_price, 6) == 1.0
    assert round(session.realized_pnl_usdc, 10) == 6.0
    assert round(session.return_on_open_notional_pct, 6) == 150.0
    assert result.session_diagnostics.chart_eligible_sessions == 1


def test_unresolved_closed_market_force_closes_terminal_pair_at_zero():
    market = PolymarketMarket(
        slug="btc-updown-5m-4000",
        condition_id="cond4",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
        closed=True,
    )
    trades = [_trade("0x12", 3990, "BUY", "up_token", "cond4", 5, 0.4)]
    engine = ProfitEngine(fee_rate_bps=0, maker_reward_ratio=0, missing_cost_warn_qty=0.5)

    result = engine.analyze_market(
        market=market,
        taker_trades=trades,
        all_trades=trades,
        split_activities=[],
        redeem_activities=[],
    )

    assert len(result.trade_sessions) == 1
    session = result.trade_sessions[0]
    assert any(w.code == "CLOSED_MARKET_UNKNOWN_OUTCOME" for w in result.warnings)
    assert result.session_diagnostics.total_detected_sessions == 1
    assert result.session_diagnostics.chart_eligible_sessions == 1
    assert round(session.close_avg_price, 6) == 0.0
    assert round(session.realized_pnl_usdc, 10) == -2.0
    assert round(session.return_on_open_notional_pct, 6) == -100.0
    assert "TERMINAL_FORCE_ZERO_CLOSE" in session.warning_codes


def test_partial_boundary_matching_uses_buy_tail_sell_head_and_zero_closes_residual():
    market = PolymarketMarket(
        slug="btc-updown-5m-5000",
        condition_id="cond5",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
    )
    trades = [
        _trade("0x01", 5000, "BUY", "up_token", "cond5", 10, 0.2),
        _trade("0x02", 5010, "BUY", "up_token", "cond5", 10, 0.4),
        _trade("0x03", 5020, "SELL", "up_token", "cond5", 15, 0.6),
    ]
    engine = ProfitEngine(fee_rate_bps=0, maker_reward_ratio=0, missing_cost_warn_qty=0.5)

    result = engine.analyze_market(
        market=market,
        taker_trades=trades,
        all_trades=trades,
        split_activities=[],
        redeem_activities=[],
    )

    assert len(result.trade_sessions) == 2
    matched = next(session for session in result.trade_sessions if "TERMINAL_FORCE_ZERO_CLOSE" not in session.warning_codes)
    residual = next(session for session in result.trade_sessions if "TERMINAL_FORCE_ZERO_CLOSE" in session.warning_codes)

    assert round(matched.open_qty, 10) == 15.0
    assert round(matched.open_avg_price, 6) == 0.333333
    assert round(matched.close_avg_price, 6) == 0.6
    assert round(matched.open_notional_usdc, 10) == 5.0
    assert round(matched.close_notional_usdc, 10) == 9.0
    assert round(matched.realized_pnl_usdc, 10) == 4.0
    assert round(matched.return_on_open_notional_pct, 6) == 80.0

    assert round(residual.open_qty, 10) == 5.0
    assert round(residual.open_avg_price, 6) == 0.2
    assert round(residual.close_avg_price, 6) == 0.0
    assert round(residual.realized_pnl_usdc, 10) == -1.0
    assert round(residual.return_on_open_notional_pct, 6) == -100.0
    assert "TERMINAL_FORCE_ZERO_CLOSE" in residual.warning_codes


def test_session_bucket_aggregation_includes_weighted_returns_and_half_win_ties():
    sessions = [
        TradeSession(
            market_slug="btc-updown-5m-1000",
            start_timestamp=1000,
            end_timestamp=1010,
            open_timestamp=1000,
            open_hour_utc=0,
            open_avg_price=0.431,
            open_notional_usdc=1,
            open_qty=2,
            close_avg_price=0.44,
            close_notional_usdc=1.2,
            close_qty=2.7272727273,
            peak_position_notional_usdc=15,
            realized_pnl_usdc=1,
            return_on_open_notional_pct=100,
            event_count=2,
            has_trade_entry=True,
            is_chart_eligible=True,
        ),
        TradeSession(
            market_slug="btc-updown-5m-1010",
            start_timestamp=1010,
            end_timestamp=1020,
            open_timestamp=1010,
            open_hour_utc=0,
            open_avg_price=0.439,
            open_notional_usdc=9,
            open_qty=18,
            close_avg_price=0.439,
            close_notional_usdc=9,
            close_qty=20.5011389522,
            peak_position_notional_usdc=15,
            realized_pnl_usdc=0,
            return_on_open_notional_pct=0,
            event_count=2,
            has_trade_entry=True,
            is_chart_eligible=True,
        ),
        TradeSession(
            market_slug="btc-updown-5m-1020",
            start_timestamp=1020,
            end_timestamp=1030,
            open_timestamp=1020,
            open_hour_utc=0,
            open_avg_price=0.52,
            open_notional_usdc=5,
            open_qty=10,
            close_avg_price=0.48,
            close_notional_usdc=4.8,
            close_qty=10,
            peak_position_notional_usdc=15,
            realized_pnl_usdc=0.5,
            return_on_open_notional_pct=10,
            event_count=2,
            has_trade_entry=True,
            is_chart_eligible=True,
        ),
    ]
    diagnostics = SessionAnalyticsDiagnostics(
        total_detected_sessions=3,
        closed_sessions=3,
        chart_eligible_sessions=3,
    )

    analytics = _build_session_analytics(sessions, diagnostics)
    hour_bucket = analytics.open_hour_buckets[0]
    price_bucket = next(bucket for bucket in analytics.open_price_buckets if bucket.bin_index == 43)
    peak_bucket = next(bucket for bucket in analytics.open_peak_notional_buckets if bucket.bin_index == 1)

    assert round(hour_bucket.weighted_return_on_open_notional_pct, 6) == 10.0
    assert round(hour_bucket.average_return_on_open_notional_pct, 6) == 36.666667
    assert round(hour_bucket.win_rate_pct, 6) == 83.333333
    assert hour_bucket.session_count == 3
    assert round(price_bucket.weighted_return_on_open_notional_pct, 6) == 10.0
    assert round(price_bucket.average_return_on_open_notional_pct, 6) == 50.0
    assert round(price_bucket.win_rate_pct, 6) == 75.0
    assert price_bucket.session_count == 2
    assert peak_bucket.session_count == 3
    assert round(peak_bucket.sum_peak_position_notional_usdc, 6) == 45.0
    assert round(peak_bucket.weighted_return_on_open_notional_pct, 6) == 10.0


def test_session_analytics_can_split_all_sessions_into_yes_and_no_groups():
    sessions = [
        TradeSession(
            market_slug="btc-updown-5m-1000",
            start_timestamp=1000,
            end_timestamp=1010,
            entry_side="YES",
            entry_outcome="Yes",
            open_timestamp=1000,
            open_hour_utc=0,
            open_avg_price=0.43,
            open_notional_usdc=2,
            open_qty=4,
            close_avg_price=0.55,
            close_notional_usdc=2.4,
            close_qty=4,
            peak_position_notional_usdc=4,
            realized_pnl_usdc=0.4,
            return_on_open_notional_pct=20,
            event_count=2,
            has_trade_entry=True,
            is_chart_eligible=True,
        ),
        TradeSession(
            market_slug="btc-updown-5m-1010",
            start_timestamp=1010,
            end_timestamp=1020,
            entry_side="NO",
            entry_outcome="No",
            open_timestamp=1010,
            open_hour_utc=1,
            open_avg_price=0.61,
            open_notional_usdc=3,
            open_qty=5,
            close_avg_price=0.4,
            close_notional_usdc=2,
            close_qty=5,
            peak_position_notional_usdc=6,
            realized_pnl_usdc=-1,
            return_on_open_notional_pct=-33.333333,
            event_count=2,
            has_trade_entry=True,
            is_chart_eligible=True,
        ),
    ]

    analytics_by_side = _build_session_analytics_by_side(sessions)

    assert analytics_by_side["YES"].diagnostics.total_detected_sessions == 1
    assert analytics_by_side["YES"].trade_sessions[0].entry_side == "YES"
    assert analytics_by_side["YES"].open_hour_buckets[0].session_count == 1

    assert analytics_by_side["NO"].diagnostics.total_detected_sessions == 1
    assert analytics_by_side["NO"].trade_sessions[0].entry_side == "NO"
    assert analytics_by_side["NO"].open_hour_buckets[1].session_count == 1


def test_profit_engine_builds_true_side_pairs_for_mixed_yes_no_market():
    market = PolymarketMarket(
        slug="btc-updown-5m-2000",
        condition_id="cond_mixed",
        up_token_id="yes_token",
        down_token_id="no_token",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
    )
    trades = [
        _trade("0x01", 2000, "BUY", "yes_token", "cond_mixed", 10, 0.20),
        _trade("0x02", 2010, "BUY", "no_token", "cond_mixed", 10, 0.70),
        _trade("0x03", 2020, "SELL", "yes_token", "cond_mixed", 10, 0.40),
        _trade("0x04", 2030, "SELL", "no_token", "cond_mixed", 10, 0.50),
    ]
    engine = ProfitEngine(fee_rate_bps=0, maker_reward_ratio=0, missing_cost_warn_qty=0.5)

    result = engine.analyze_market(
        market=market,
        taker_trades=trades,
        all_trades=trades,
        split_activities=[],
        redeem_activities=[],
    )

    assert len(result.trade_sessions) == 2
    assert {session.entry_side for session in result.trade_sessions} == {"YES", "NO"}

    yes_sessions = result.side_trade_sessions["YES"]
    no_sessions = result.side_trade_sessions["NO"]
    assert len(yes_sessions) == 1
    assert len(no_sessions) == 1
    assert yes_sessions[0].entry_side == "YES"
    assert no_sessions[0].entry_side == "NO"
    assert yes_sessions[0].realized_pnl_usdc > 0
    assert no_sessions[0].realized_pnl_usdc < 0
