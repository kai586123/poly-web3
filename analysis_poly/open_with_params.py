from __future__ import annotations

import argparse
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from analysis_poly.logging_config import configure_logging
    from analysis_poly.web import app
else:
    from .logging_config import configure_logging
    from .web import app


def _to_datetime_text(unix_ts: int) -> str:
    return datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M")


def _browser_host(host: str) -> str:
    if host == "0.0.0.0":
        return "localhost"
    return host


def _build_bootstrap_query(args: argparse.Namespace) -> dict[str, str]:
    params: dict[str, str] = {}

    mapping = {
        "address": "address",
        "symbols": "symbols",
        "intervals": "intervals",
        "start_time": "start_time",
        "end_time": "end_time",
        "fee_rate_bps": "fee_rate_bps",
        "missing_cost_warn_qty": "missing_cost_warn_qty",
        "maker_reward_ratio": "maker_reward_ratio",
        "concurrency": "concurrency",
        "page_limit": "page_limit",
    }
    for arg_key, query_key in mapping.items():
        value = getattr(args, arg_key)
        if value is None:
            continue
        params[query_key] = str(value)

    if args.start_ts is not None and "start_time" not in params:
        params["start_time"] = _to_datetime_text(args.start_ts)
    if args.end_ts is not None and "end_time" not in params:
        params["end_time"] = _to_datetime_text(args.end_ts)

    has_analysis_fields = any(
        key in params
        for key in {
            "address",
            "symbols",
            "intervals",
            "start_time",
            "end_time",
            "fee_rate_bps",
            "missing_cost_warn_qty",
            "maker_reward_ratio",
            "concurrency",
            "page_limit",
        }
    )
    if args.auto_start or has_analysis_fields:
        params["auto_start"] = "1"

    return params


def _build_browser_url(args: argparse.Namespace) -> str:
    host = _browser_host(args.host)
    base = f"http://{host}:{args.port}/"
    params = _build_bootstrap_query(args)
    if not params:
        return base
    return f"{base}?{urllib.parse.urlencode(params)}"


def _open_browser_when_ready(url: str, probe_url: str, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe_url, timeout=0.8):
                webbrowser.open(url)
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    webbrowser.open(url)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start web server and open browser with bootstrap params")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for web server")
    parser.add_argument("--port", type=int, default=8000, help="Bind port for web server")
    parser.add_argument("--browser-timeout-sec", type=float, default=20.0, help="Wait timeout for browser auto-open")

    parser.add_argument("--address")
    parser.add_argument("--symbols", help='Comma-separated, e.g. "btc,eth,sol"')
    parser.add_argument("--intervals", help='Comma-separated, e.g. "5,15"')
    parser.add_argument("--start-time", help='Local datetime, format "YYYY-MM-DD HH:MM"')
    parser.add_argument("--end-time", help='Local datetime, format "YYYY-MM-DD HH:MM"')
    parser.add_argument("--start-ts", type=int, help="Unix timestamp (seconds), used when --start-time is missing")
    parser.add_argument("--end-ts", type=int, help="Unix timestamp (seconds), used when --end-time is missing")
    parser.add_argument("--fee-rate-bps", type=float)
    parser.add_argument("--missing-cost-warn-qty", type=float)
    parser.add_argument("--maker-reward-ratio", type=float)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--page-limit", type=int)
    parser.add_argument("--auto-start", action="store_true", help="Force auto start analysis in frontend")
    return parser


def main() -> None:
    import uvicorn

    args = _build_arg_parser().parse_args()
    configure_logging()

    browser_host = _browser_host(args.host)
    probe_url = f"http://{browser_host}:{args.port}/"
    url = _build_browser_url(args)
    threading.Thread(
        target=_open_browser_when_ready,
        args=(url, probe_url, max(1.0, args.browser_timeout_sec)),
        daemon=True,
    ).start()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
