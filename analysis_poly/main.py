from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from analysis_poly.logging_config import configure_logging
    from analysis_poly.web import app
else:
    from .logging_config import configure_logging
    from .web import app


def run(host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    configure_logging()
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    run()


if __name__ == "__main__":
    main()
