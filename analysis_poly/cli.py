from __future__ import annotations

import argparse

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from analysis_poly.main import run
else:
    from .main import run


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run analysis-poly web server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for web server")
    parser.add_argument("--port", type=int, default=8000, help="Bind port for web server")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
