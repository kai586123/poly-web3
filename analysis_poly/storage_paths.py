from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "poly-web3"


def default_cache_root() -> Path:
    override = os.getenv("ANALYSIS_POLY_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "darwin":
        base = Path("~/Library/Caches").expanduser()
    elif os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or (Path.home() / "AppData/Local")).expanduser()
    else:
        base = Path(os.getenv("XDG_CACHE_HOME") or (Path.home() / ".cache")).expanduser()
    return (base / APP_NAME).resolve()


def default_data_root() -> Path:
    override = os.getenv("ANALYSIS_POLY_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "darwin":
        base = Path("~/Library/Application Support").expanduser()
    elif os.name == "nt":
        base = Path(os.getenv("APPDATA") or (Path.home() / "AppData/Roaming")).expanduser()
    else:
        base = Path(os.getenv("XDG_DATA_HOME") or (Path.home() / ".local/share")).expanduser()
    return (base / APP_NAME).resolve()


def default_reports_dir() -> Path:
    override = os.getenv("ANALYSIS_POLY_REPORTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (default_data_root() / "reports").resolve()


def default_market_metadata_cache_dir() -> Path:
    return (default_cache_root() / "market_by_slug").resolve()


def default_market_result_cache_dir() -> Path:
    return (default_cache_root() / "address_market_results").resolve()
