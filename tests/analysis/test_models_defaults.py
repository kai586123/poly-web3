import pytest

from analysis_poly.models import AnalysisRequest


def test_analysis_request_default_concurrency_is_5():
    req = AnalysisRequest(
        address="0xabc",
        start_ts=100,
        end_ts=200,
        symbols=["btc"],
        intervals=[5],
    )
    assert req.concurrency == 5


def test_analysis_request_address_only_requires_0x_prefix():
    req = AnalysisRequest(
        address="0x1",
        start_ts=100,
        end_ts=200,
        symbols=["btc"],
        intervals=[5],
    )
    assert req.address == "0x1"


def test_analysis_request_address_rejects_non_0x_prefix():
    with pytest.raises(ValueError, match="address must start with 0x"):
        AnalysisRequest(
            address="abc",
            start_ts=100,
            end_ts=200,
            symbols=["btc"],
            intervals=[5],
        )
