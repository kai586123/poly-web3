from analysis_poly.analyzer import _has_market_trade_activity
from analysis_poly.models import MarketReport, TokenReport


def test_has_market_trade_activity_false_for_no_trade_tokens():
    report = MarketReport(
        market_slug="btc-updown-5m-1",
        condition_id="cond",
        up_token_id="up",
        down_token_id="down",
        tokens=[
            TokenReport(token_id="up", outcome="Up", trade_count=0),
            TokenReport(token_id="down", outcome="Down", trade_count=0),
        ],
    )
    assert _has_market_trade_activity(report) is False


def test_has_market_trade_activity_true_when_any_token_traded():
    report = MarketReport(
        market_slug="btc-updown-5m-1",
        condition_id="cond",
        up_token_id="up",
        down_token_id="down",
        tokens=[
            TokenReport(token_id="up", outcome="Up", trade_count=1),
            TokenReport(token_id="down", outcome="Down", trade_count=0),
        ],
    )
    assert _has_market_trade_activity(report) is True
