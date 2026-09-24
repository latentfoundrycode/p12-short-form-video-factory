"""The `sfvf` launch command: start the local server and open the browser."""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from app.paths import APP_ROOT


def read_version() -> str:
    return (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _run_uvicorn(host: str, port: int) -> None:
    uvicorn.run("app.main:app", host=host, port=port)


def _open_browser(url: str) -> None:
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sfvf",
        description="Start the SFVF local server and open it in the browser.",
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="start the server without opening a browser",
    )
    return parser


def serve(host: str, port: int, *, open_browser: bool) -> None:
    if open_browser:
        _open_browser(f"http://{host}:{port}")
    _run_uvicorn(host, port)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(read_version())
        return 0
    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


def _action_type(action: argparse.Action) -> str:
    typ = action.type
    if typ is None:
        return "bool" if action.const is True else "str"
    return getattr(typ, "__name__", "str")


def _action_default(action: argparse.Action) -> object:
    default = action.default
    if default is argparse.SUPPRESS:
        return None
    return default


def _option_ref(action: argparse.Action) -> dict[str, object]:
    return {
        "default": _action_default(action),
        "flags": list(action.option_strings),
        "help": action.help or "",
        "type": _action_type(action),
    }


def cli_reference() -> dict[str, object]:
    parser = build_parser()
    options = [_option_ref(action) for action in parser._actions if action.option_strings]
    return {
        "description": parser.description or "",
        "options": options,
        "prog": parser.prog,
        "version": read_version(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
