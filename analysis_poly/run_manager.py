from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException
from loguru import logger

from .analyzer import AnalyzerHooks, PolymarketProfitAnalyzer
from .models import (
    AnalysisReport,
    AnalysisRequest,
    RunCreated,
    RunState,
    RunStatus,
    RunStopAck,
    WarningItem,
    utc_now,
)


@dataclass
class RunContext:
    state: RunState
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    result: AnalysisReport | None = None
    task: asyncio.Task | None = None


class RunHooks(AnalyzerHooks):
    def __init__(self, manager: "RunManager", run_id: str):
        self._manager = manager
        self._run_id = run_id

    async def on_run_started(self, total_markets: int) -> None:
        ctx = self._manager._runs[self._run_id]
        ctx.state.progress_total = total_markets
        await self._manager._emit(
            self._run_id,
            "run_started",
            {"run_id": self._run_id, "progress_total": total_markets},
        )

    async def on_progress(self, current: int, total: int, market_slug: str) -> None:
        ctx = self._manager._runs[self._run_id]
        ctx.state.progress_current = current
        ctx.state.progress_total = total
        ctx.state.message = market_slug
        await self._manager._emit(
            self._run_id,
            "progress",
            {
                "current": current,
                "total": total,
                "market_slug": market_slug,
            },
        )

    async def on_warning(self, warning: WarningItem) -> None:
        logger.warning(
            "warning run_id={} code={} market={} token={} msg={}",
            self._run_id,
            warning.code,
            warning.market_slug or "-",
            warning.token_id or "-",
            warning.message,
        )
        await self._manager._emit(self._run_id, "warning", warning.model_dump())

    async def on_total_point(self, timestamp: int, delta: float, cumulative: float) -> None:
        await self._manager._emit(
            self._run_id,
            "point_total",
            {
                "timestamp": timestamp,
                "delta_realized_pnl_usdc": delta,
                "cumulative_realized_pnl_usdc": cumulative,
            },
        )

    async def on_market_point(
        self, market_slug: str, timestamp: int, delta: float, cumulative: float
    ) -> None:
        await self._manager._emit(
            self._run_id,
            "point_market",
            {
                "market_slug": market_slug,
                "timestamp": timestamp,
                "delta_realized_pnl_usdc": delta,
                "cumulative_realized_pnl_usdc": cumulative,
            },
        )

    async def on_total_point_no_fee(self, timestamp: int, delta: float, cumulative: float) -> None:
        await self._manager._emit(
            self._run_id,
            "point_total_no_fee",
            {
                "timestamp": timestamp,
                "delta_realized_pnl_usdc": delta,
                "cumulative_realized_pnl_usdc": cumulative,
            },
        )

    async def on_market_point_no_fee(
        self, market_slug: str, timestamp: int, delta: float, cumulative: float
    ) -> None:
        await self._manager._emit(
            self._run_id,
            "point_market_no_fee",
            {
                "market_slug": market_slug,
                "timestamp": timestamp,
                "delta_realized_pnl_usdc": delta,
                "cumulative_realized_pnl_usdc": cumulative,
            },
        )


class RunManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._runs: dict[str, RunContext] = {}
        self._active_run_id: str | None = None
        self._analyzer = PolymarketProfitAnalyzer()

    async def create_run(self, req: AnalysisRequest) -> RunCreated:
        async with self._lock:
            if self._active_run_id:
                active = self._runs.get(self._active_run_id)
                if active and active.state.status in {
                    RunStatus.PENDING,
                    RunStatus.RUNNING,
                    RunStatus.STOPPING,
                }:
                    raise HTTPException(status_code=409, detail="another run is in progress")

            run_id = uuid.uuid4().hex
            state = RunState(run_id=run_id, status=RunStatus.PENDING)
            ctx = RunContext(state=state)
            self._runs[run_id] = ctx
            self._active_run_id = run_id

            ctx.task = asyncio.create_task(self._execute_run(run_id, req))
            logger.info(
                "create run run_id={} address={} range=[{}, {}] symbols={} intervals={}",
                run_id,
                req.address,
                req.start_ts,
                req.end_ts,
                ",".join(req.symbols),
                ",".join(str(v) for v in req.intervals),
            )
            return RunCreated(run_id=run_id, status=state.status)

    async def stop_run(self, run_id: str) -> RunStopAck:
        ctx = self._runs.get(run_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="run not found")

        if ctx.state.status in {RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED}:
            return RunStopAck(run_id=run_id, status=ctx.state.status)

        ctx.stop_event.set()
        ctx.state.status = RunStatus.STOPPING
        logger.warning("stop requested run_id={}", run_id)
        await self._emit(run_id, "progress", {"message": "stopping requested"})
        return RunStopAck(run_id=run_id, status=ctx.state.status)

    async def get_result(self, run_id: str) -> AnalysisReport:
        ctx = self._runs.get(run_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="run not found")

        if not ctx.result:
            raise HTTPException(status_code=202, detail="run not finished")
        return ctx.result

    async def get_state(self, run_id: str) -> RunState:
        ctx = self._runs.get(run_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="run not found")
        return ctx.state

    async def stream(self, run_id: str):
        ctx = self._runs.get(run_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="run not found")

        while True:
            if ctx.task and ctx.task.done() and ctx.queue.empty():
                break

            try:
                payload = await asyncio.wait_for(ctx.queue.get(), timeout=10)
                yield payload
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    async def _execute_run(self, run_id: str, req: AnalysisRequest) -> None:
        ctx = self._runs[run_id]
        hooks = RunHooks(self, run_id)

        try:
            ctx.state.status = RunStatus.RUNNING
            ctx.state.started_at = utc_now()
            logger.info("run started run_id={}", run_id)

            report = await self._analyzer.run(req=req, stop_event=ctx.stop_event, hooks=hooks)

            output_dir = Path(req.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            suffix = f"{run_id}_{'partial' if report.is_partial else 'final'}"

            json_path = self._analyzer.save_json(report, str(output_dir / f"pnl_summary_{suffix}.json"))
            total_csv_path = self._analyzer.save_total_curve_csv(
                report, str(output_dir / f"pnl_total_curve_{suffix}.csv")
            )
            market_csv_path = self._analyzer.save_market_curve_csv(
                report, str(output_dir / f"pnl_market_curve_{suffix}.csv")
            )

            report.artifacts = {
                "json": json_path,
                "total_curve_csv": total_csv_path,
                "market_curve_csv": market_csv_path,
            }

            ctx.result = report
            ctx.state.ended_at = utc_now()

            if report.is_partial:
                ctx.state.status = RunStatus.STOPPED
                logger.warning("run stopped run_id={} (partial result saved)", run_id)
                await self._emit(
                    run_id,
                    "stopped",
                    {
                        "run_id": run_id,
                        "status": ctx.state.status,
                        "artifacts": self._to_public_artifact_paths(report.artifacts),
                    },
                )
            else:
                ctx.state.status = RunStatus.COMPLETED
                logger.info("run completed run_id={} markets_processed={}", run_id, report.summary.markets_processed)
                await self._emit(
                    run_id,
                    "completed",
                    {
                        "run_id": run_id,
                        "status": ctx.state.status,
                        "artifacts": self._to_public_artifact_paths(report.artifacts),
                        "summary": report.summary.model_dump(),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            ctx.state.status = RunStatus.FAILED
            ctx.state.ended_at = utc_now()
            logger.exception("run failed run_id={} error={}", run_id, exc)
            await self._emit(run_id, "run_error", {"message": str(exc)})
        finally:
            async with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None

    async def _emit(self, run_id: str, event_name: str, data: dict) -> None:
        ctx = self._runs.get(run_id)
        if not ctx:
            return
        payload = self._format_sse(event_name, data)
        await ctx.queue.put(payload)

    @staticmethod
    def _format_sse(event_name: str, data: dict) -> str:
        return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def _to_public_artifact_paths(artifacts: dict[str, str]) -> dict[str, str]:
        public: dict[str, str] = {}
        for key, path in artifacts.items():
            filename = Path(path).name
            public[key] = f"/reports/{filename}"
        return public
