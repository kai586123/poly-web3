from datetime import datetime, timezone

from analysis_poly.models import ActivityRecord, PolymarketMarket, TradeRecord
from analysis_poly.profit_engine import ProfitEngine, _fee_adjust


def test_fee_adjust_basic():
    adjusted, fee_token, fee_usdc = _fee_adjust(100.0, 0.5, 1000)
    assert adjusted < 100.0
    assert fee_token == 100.0 - adjusted
    assert fee_usdc == fee_token * 0.5


def test_profit_engine_taker_buy_sell_and_redeem_warning():
    market = PolymarketMarket(
        slug="btc-updown-5m-1000",
        condition_id="cond1",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
    )

    taker_buy = TradeRecord.model_validate(
        {
            "transactionHash": "0x01",
            "timestamp": 1000,
            "side": "BUY",
            "asset": "up_token",
            "conditionId": "cond1",
            "size": 10,
            "price": 0.5,
        }
    )
    taker_sell = TradeRecord.model_validate(
        {
            "transactionHash": "0x02",
            "timestamp": 1010,
            "side": "SELL",
            "asset": "up_token",
            "conditionId": "cond1",
            "size": 5,
            "price": 0.6,
        }
    )
    redeem = ActivityRecord.model_validate(
        {
            "transactionHash": "0x03",
            "timestamp": 1020,
            "type": "REDEEM",
            "conditionId": "cond1",
            "size": 1,
            "usdcSize": 1,
        }
    )

    engine = ProfitEngine(fee_rate_bps=1000, maker_reward_ratio=0.2, missing_cost_warn_qty=0.5)
    report, deltas, warnings = engine.process_market(
        market=market,
        taker_trades=[taker_buy, taker_sell],
        all_trades=[taker_buy, taker_sell],
        split_activities=[],
        redeem_activities=[redeem],
    )

    assert report.market_slug == "btc-updown-5m-1000"
    assert len(deltas) >= 1
    # outcomePrices not unique winner => redeem skipped warning
    assert any(w.code == "REDEEM_SKIP_UNKNOWN_WINNER" for w in warnings)


def test_profit_engine_split_allocation():
    market = PolymarketMarket(
        slug="eth-updown-15m-2000",
        condition_id="cond2",
        up_token_id="up",
        down_token_id="down",
        outcomes=["Up", "Down"],
        outcome_prices=[1, 0],
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

    engine = ProfitEngine(fee_rate_bps=1000, maker_reward_ratio=0.2, missing_cost_warn_qty=0.5)
    report, _, _ = engine.process_market(
        market=market,
        taker_trades=[],
        all_trades=[],
        split_activities=[split],
        redeem_activities=[],
    )

    up = next(t for t in report.tokens if t.token_id == "up")
    down = next(t for t in report.tokens if t.token_id == "down")
    assert up.split_qty == 3
    assert down.split_qty == 3


def test_maker_reward_skipped_for_today_market_and_kept_for_history():
    day_start = int(
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    today_market = PolymarketMarket(
        slug=f"btc-updown-5m-{day_start + 300}",
        condition_id="today_cond",
        up_token_id="up_today",
        down_token_id="down_today",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
    )
    history_market = PolymarketMarket(
        slug=f"btc-updown-5m-{day_start - 300}",
        condition_id="history_cond",
        up_token_id="up_hist",
        down_token_id="down_hist",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
    )

    maker_buy_today = TradeRecord.model_validate(
        {
            "transactionHash": "0xmaker_today",
            "timestamp": day_start + 400,
            "side": "BUY",
            "asset": "up_today",
            "conditionId": "today_cond",
            "size": 100,
            "price": 0.5,
        }
    )
    maker_buy_hist = TradeRecord.model_validate(
        {
            "transactionHash": "0xmaker_hist",
            "timestamp": day_start - 200,
            "side": "BUY",
            "asset": "up_hist",
            "conditionId": "history_cond",
            "size": 100,
            "price": 0.5,
        }
    )

    engine = ProfitEngine(fee_rate_bps=1000, maker_reward_ratio=0.2, missing_cost_warn_qty=0.5)

    today_report, _, today_warnings = engine.process_market(
        market=today_market,
        taker_trades=[],
        all_trades=[maker_buy_today],
        split_activities=[],
        redeem_activities=[],
    )
    hist_report, _, _ = engine.process_market(
        market=history_market,
        taker_trades=[],
        all_trades=[maker_buy_hist],
        split_activities=[],
        redeem_activities=[],
    )

    assert today_report.maker_reward_usdc == 0
    assert any(w.code == "MAKER_REWARD_DEFERRED_TODAY" for w in today_warnings)
    assert hist_report.maker_reward_usdc > 0


def test_closed_market_without_redeem_settles_remaining_position_by_outcome_prices():
    market = PolymarketMarket(
        slug="btc-updown-5m-3000",
        condition_id="cond3",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[1, 0],
        closed=True,
    )

    taker_buy = TradeRecord.model_validate(
        {
            "transactionHash": "0x11",
            "timestamp": 2990,
            "side": "BUY",
            "asset": "up_token",
            "conditionId": "cond3",
            "size": 10,
            "price": 0.4,
        }
    )

    engine = ProfitEngine(fee_rate_bps=1000, maker_reward_ratio=0.2, missing_cost_warn_qty=0.5)
    report, _, warnings = engine.process_market(
        market=market,
        taker_trades=[taker_buy],
        all_trades=[taker_buy],
        split_activities=[],
        redeem_activities=[],
    )

    up = next(t for t in report.tokens if t.token_id == "up_token")
    assert up.ending_position_qty == 0
    assert report.ending_position_up == 0
    assert report.realized_pnl_usdc > 0
    assert up.realized_pnl_usdc > 0
    assert not any(w.code == "CLOSED_MARKET_UNKNOWN_OUTCOME" for w in warnings)


def test_closed_market_without_redeem_losing_position_counts_as_loss():
    market = PolymarketMarket(
        slug="btc-updown-5m-3500",
        condition_id="cond35",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[0, 1],
        closed=True,
    )

    taker_buy = TradeRecord.model_validate(
        {
            "transactionHash": "0x115",
            "timestamp": 3490,
            "side": "BUY",
            "asset": "up_token",
            "conditionId": "cond35",
            "size": 10,
            "price": 0.4,
        }
    )

    engine = ProfitEngine(fee_rate_bps=1000, maker_reward_ratio=0.2, missing_cost_warn_qty=0.5)
    report, _, warnings = engine.process_market(
        market=market,
        taker_trades=[taker_buy],
        all_trades=[taker_buy],
        split_activities=[],
        redeem_activities=[],
    )

    up = next(t for t in report.tokens if t.token_id == "up_token")
    assert up.ending_position_qty == 0
    assert up.realized_pnl_usdc < 0
    assert report.realized_pnl_usdc < 0
    assert not any(w.code == "CLOSED_MARKET_UNKNOWN_OUTCOME" for w in warnings)


def test_closed_market_without_resolved_outcome_prices_warns_and_keeps_position():
    market = PolymarketMarket(
        slug="btc-updown-5m-4000",
        condition_id="cond4",
        up_token_id="up_token",
        down_token_id="down_token",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
        closed=True,
    )

    taker_buy = TradeRecord.model_validate(
        {
            "transactionHash": "0x12",
            "timestamp": 3990,
            "side": "BUY",
            "asset": "up_token",
            "conditionId": "cond4",
            "size": 5,
            "price": 0.4,
        }
    )

    engine = ProfitEngine(fee_rate_bps=1000, maker_reward_ratio=0.2, missing_cost_warn_qty=0.5)
    report, _, warnings = engine.process_market(
        market=market,
        taker_trades=[taker_buy],
        all_trades=[taker_buy],
        split_activities=[],
        redeem_activities=[],
    )

    up = next(t for t in report.tokens if t.token_id == "up_token")
    assert up.ending_position_qty > 0
    assert any(w.code == "CLOSED_MARKET_UNKNOWN_OUTCOME" for w in warnings)
