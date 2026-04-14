import pytest

from analysis_poly.models import PolymarketMarket, TradeRecord
from analysis_poly.profit_engine import (
    PnlDelta,
    ProfitEngine,
    TurnoverDelta,
    build_pnl_turnover_timeline,
    build_turnover_curve,
)


def test_build_turnover_curve_aggregates_same_timestamp():
    deltas = [
        TurnoverDelta(timestamp=100, market_slug="m1", delta_turnover_usdc=2.0),
        TurnoverDelta(timestamp=100, market_slug="m1", delta_turnover_usdc=3.0),
        TurnoverDelta(timestamp=200, market_slug="m1", delta_turnover_usdc=1.0),
    ]
    curve = build_turnover_curve(deltas)
    assert curve == [
        (100, 5.0, 5.0),
        (200, 1.0, 6.0),
    ]


def test_build_pnl_turnover_timeline_includes_buy_only_turnover_steps():
    """BUY adds turnover without PnL delta; merged timeline must still step turnover."""
    start_ts = 50
    turnover = [
        TurnoverDelta(timestamp=100, market_slug="m", delta_turnover_usdc=10.0),
    ]
    pnl_net: list[PnlDelta] = []
    pnl_nf: list[PnlDelta] = []
    tl = build_pnl_turnover_timeline(start_ts, pnl_net, pnl_nf, turnover)
    assert tl[0] == (50, 0.0, 0.0, 0.0)
    assert tl[1] == (100, 10.0, 0.0, 0.0)


def test_build_pnl_turnover_timeline_no_prepend_when_first_event_at_start():
    start_ts = 100
    turnover = [TurnoverDelta(timestamp=100, market_slug="m", delta_turnover_usdc=1.0)]
    tl = build_pnl_turnover_timeline(start_ts, [], [], turnover)
    assert len(tl) == 1
    assert tl[0] == (100, 1.0, 0.0, 0.0)


def test_build_pnl_turnover_timeline_merges_pnl_and_turnover_timestamps():
    pnl = [
        PnlDelta(timestamp=200, market_slug="m", token_id="t", delta_pnl_usdc=-1.0),
    ]
    turnover = [
        TurnoverDelta(timestamp=100, market_slug="m", delta_turnover_usdc=5.0),
    ]
    tl = build_pnl_turnover_timeline(0, pnl, pnl, turnover)
    assert tl == [
        (0, 0.0, 0.0, 0.0),
        (100, 5.0, 0.0, 0.0),
        (200, 5.0, -1.0, -1.0),
    ]


def test_analyze_market_emits_turnover_for_buy_without_pnl_delta():
    market = PolymarketMarket(
        slug="btc-updown-5m-1000",
        condition_id="cond_d",
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
            "conditionId": "cond_d",
            "size": 10,
            "price": 0.5,
        }
    )
    engine = ProfitEngine(fee_rate_bps=72, maker_reward_ratio=0.0, missing_cost_warn_qty=0.5)
    replay = engine.analyze_market(
        market=market,
        taker_trades=[taker_buy],
        all_trades=[taker_buy],
        split_activities=[],
        redeem_activities=[],
    )
    assert replay.deltas == []
    assert len(replay.turnover_deltas) == 1
    assert replay.turnover_deltas[0].delta_turnover_usdc == pytest.approx(5.0)
