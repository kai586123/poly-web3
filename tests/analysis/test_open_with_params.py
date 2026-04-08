import argparse

from analysis_poly.open_with_params import _build_bootstrap_query, _build_browser_url, _to_datetime_text


def _args(**kwargs):
    defaults = dict(
        host="0.0.0.0",
        port=8000,
        browser_timeout_sec=20.0,
        address=None,
        symbols=None,
        intervals=None,
        start_time=None,
        end_time=None,
        start_ts=None,
        end_ts=None,
        fee_rate_bps=None,
        missing_cost_warn_qty=None,
        maker_reward_ratio=None,
        concurrency=None,
        page_limit=None,
        auto_start=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_build_bootstrap_query_with_explicit_fields_sets_auto_start():
    args = _args(
        address="0xabc",
        symbols="btc,eth",
        intervals="5,15",
        start_time="2026-03-01 00:00",
        end_time="2026-03-02 00:00",
        concurrency=8,
    )
    query = _build_bootstrap_query(args)
    assert query["address"] == "0xabc"
    assert query["symbols"] == "btc,eth"
    assert query["intervals"] == "5,15"
    assert query["start_time"] == "2026-03-01 00:00"
    assert query["end_time"] == "2026-03-02 00:00"
    assert query["concurrency"] == "8"
    assert query["auto_start"] == "1"


def test_build_bootstrap_query_uses_timestamp_when_text_missing():
    args = _args(start_ts=1709251200, end_ts=1709337600)
    query = _build_bootstrap_query(args)
    assert query["start_time"] == _to_datetime_text(1709251200)
    assert query["end_time"] == _to_datetime_text(1709337600)
    assert query["auto_start"] == "1"


def test_build_browser_url_without_params_returns_base_url():
    args = _args()
    assert _build_browser_url(args) == "http://localhost:8000/"
