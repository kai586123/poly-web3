import asyncio

import pytest
from fastapi import HTTPException

from analysis_poly.models import AnalysisReport, AnalysisRequest, SummaryStats
from analysis_poly.run_manager import RunManager


def test_single_run_lock_conflict(monkeypatch):
    async def runner():
        manager = RunManager()

        async def fake_run(req, stop_event=None, hooks=None):
            await asyncio.sleep(0.2)
            return AnalysisReport(
                request=req,
                summary=SummaryStats(markets_total=1, markets_processed=1),
                markets=[],
                total_curve=[],
                market_curves={},
                warnings=[],
                is_partial=False,
            )

        monkeypatch.setattr(manager._analyzer, "run", fake_run)

        req = AnalysisRequest(
            address="0xe00740bce98a594e26861838885ab310ec3b548c",
            start_ts=100,
            end_ts=200,
            symbols=["btc"],
            intervals=[5],
        )

        await manager.create_run(req)
        with pytest.raises(HTTPException) as exc:
            await manager.create_run(req)
        assert exc.value.status_code == 409

    asyncio.run(runner())


def test_stop_run_updates_status(monkeypatch):
    async def runner():
        manager = RunManager()

        async def fake_run(req, stop_event=None, hooks=None):
            while not stop_event.is_set():
                await asyncio.sleep(0.05)
            return AnalysisReport(
                request=req,
                summary=SummaryStats(markets_total=1, markets_processed=0),
                markets=[],
                total_curve=[],
                market_curves={},
                warnings=[],
                is_partial=True,
            )

        monkeypatch.setattr(manager._analyzer, "run", fake_run)

        req = AnalysisRequest(
            address="0xe00740bce98a594e26861838885ab310ec3b548c",
            start_ts=100,
            end_ts=200,
            symbols=["btc"],
            intervals=[5],
        )

        created = await manager.create_run(req)
        ack = await manager.stop_run(created.run_id)
        assert ack.status.name == "STOPPING"

    asyncio.run(runner())
