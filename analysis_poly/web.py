from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

from .logging_config import configure_logging
from .models import AnalysisRequest, RunCreated, RunState, RunStopAck
from .run_manager import RunManager

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
REPORTS_DIR = Path(os.getenv("ANALYSIS_POLY_REPORTS_DIR", "reports")).expanduser().resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
configure_logging()

app = FastAPI(title="Polymarket Profit Analyzer")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
run_manager = RunManager()

app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    app_js = STATIC_DIR / "dist" / "app.js"
    app_css = STATIC_DIR / "dist" / "app.css"
    static_version = str(
        int(max(app_js.stat().st_mtime if app_js.exists() else 0, app_css.stat().st_mtime if app_css.exists() else 0))
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "default_address": "",
            "default_symbols": "btc,eth,sol,xrp",
            "default_intervals": "5,15",
            "static_version": static_version,
        },
    )


@app.post("/api/runs", response_model=RunCreated)
async def create_run(req: AnalysisRequest):
    logger.info(f"create run request: {req.model_dump_json(ensure_ascii=False, indent=4)}")
    return await run_manager.create_run(req)


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str):
    generator = run_manager.stream(run_id)
    return StreamingResponse(generator, media_type="text/event-stream")


@app.post("/api/runs/{run_id}/stop", response_model=RunStopAck)
async def stop_run(run_id: str):
    return await run_manager.stop_run(run_id)


@app.get("/api/runs/{run_id}/result")
async def run_result(run_id: str):
    return await run_manager.get_result(run_id)


@app.get("/api/runs/{run_id}/state", response_model=RunState)
async def run_state(run_id: str):
    return await run_manager.get_state(run_id)
