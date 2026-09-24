# TASK-pkg1 — the `sfvf` launch command + command reference

## Goal

SFVF is launched today only by a raw `uvicorn app.main:app` line. Add a first-party command the installer can put on PATH: `sfvf` starts the server on 127.0.0.1:8000 and opens the browser; `sfvf --version` prints the single-source version; `sfvf --no-browser`/`--host`/`--port` adjust it. Because this is SFVF's first command-line surface, also add the machine-readable `docs/cli-reference.json` generated from the real parser plus a CI currency check (Delivery-Conventions §4). See `docs/DELIVERY.md` for the delivery design.

## Files to create/change

1. `app/serve.py` (new) — the command.
2. `scripts/dump_cli.py` (new) — the reference generator.
3. `docs/cli-reference.json` (new) — the committed reference (generated).
4. `.github/workflows/ci.yml` — add a reference-currency step.

`VERSION` (repo root, `1.0.0`) already exists. Do not touch any test. Frozen contract: `tests/core/test_serve.py`.

## `app/serve.py`

- `read_version() -> str`: return the stripped contents of `APP_ROOT / "VERSION"` (import `APP_ROOT` from `app.paths`). This is the single version source.
- `_run_uvicorn(host: str, port: int) -> None`: call `uvicorn.run("app.main:app", host=host, port=port)`. (Thin wrapper — it is the seam the test patches; keep it a one-liner so the untested body is trivial.)
- `_open_browser(url: str) -> None`: open the browser at `url` without blocking the server — schedule it on a short `threading.Timer` that calls `webbrowser.open(url)` (so the page loads once the server is up). (Also a seam the test patches.)
- `build_parser() -> argparse.ArgumentParser`: an `argparse` parser, `prog="sfvf"`, with `--version` (store_true), `--host` (default `"127.0.0.1"`), `--port` (int, default `8000`), `--no-browser` (store_true). A clear `description`.
- `serve(host: str, port: int, *, open_browser: bool) -> None`: if `open_browser`, call `_open_browser(f"http://{host}:{port}")`; then `_run_uvicorn(host, port)`.
- `main(argv: list[str] | None = None) -> int`: parse args with `build_parser()`. If `--version`: print `read_version()` and return `0`. Otherwise call `serve(args.host, args.port, open_browser=not args.no_browser)` and return `0`. (`--help` is argparse's built-in and raises `SystemExit(0)` — leave that as is.)
- `cli_reference() -> dict`: return a machine-readable description of the command built FROM `build_parser()` (introspect it — do not hand-write a parallel copy that could drift). Include at least: the program name `"sfvf"`, a `"version"` field set to `read_version()`, and the options with their flag strings, types, defaults, and help. Shape is your call, but it must be deterministic (stable key order via `sort_keys` when serialized) and must round-trip equal to the committed `docs/cli-reference.json`.
- Add `if __name__ == "__main__": raise SystemExit(main())`.

## `scripts/dump_cli.py`

A small generator that writes `docs/cli-reference.json` from `app.serve.cli_reference()`: `json.dumps(cli_reference(), indent=2, sort_keys=True) + "\n"`, written atomically or with a plain write, to `APP_ROOT / "docs" / "cli-reference.json"`. Running it must be idempotent (no diff on a second run). Generate the committed `docs/cli-reference.json` by running it once.

## `.github/workflows/ci.yml`

Add ONE step to the existing `gate` job (do not weaken or reorder existing steps): after deps are installed, regenerate the reference and fail if it differs from the committed file — e.g. `python scripts/dump_cli.py` then `git diff --exit-code docs/cli-reference.json`. This is the §4 currency check: an added flag without a regenerated reference cannot merge.

## Constraints

- `uvicorn` and `webbrowser`/`threading` are available (uvicorn is a pinned runtime dep; the others are stdlib). No new dependency.
- Behaviour: importing `app.serve` must NOT start a server or open a browser (only `main()`/`serve()` do). `cli_reference()` and `read_version()` are pure.
- One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/core/test_serve.py` is fully green (it fails to import now — `app.serve` is new).
- `python scripts/dump_cli.py` leaves `docs/cli-reference.json` unchanged (idempotent), and the committed file matches `cli_reference()`.
- Full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .`, `-m ruff format --check .`, `-m mypy`.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for Bridge Feedback; record any defect/pitfall learning there too, for the Issues file.
