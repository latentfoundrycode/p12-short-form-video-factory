#!/usr/bin/env python
"""Cursor afterFileEdit hook: lint-fix and format edited Python files with ruff.

Reads stdin as raw bytes and decodes as utf-8-sig, because on Windows Cursor
prefixes the hook's stdin JSON with a UTF-8 BOM that breaks a plain parse.
Uses sys.executable (the venv python Cursor launched this with). Never raises,
so it can't block the agent.
"""
import json
import subprocess
import sys
from pathlib import Path

LOG = Path(__file__).with_name("lint_edit.log")


def log(msg: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main() -> None:
    raw = sys.stdin.buffer.read().decode("utf-8-sig")
    log(f"--- invoked, stdin {len(raw)} chars ---")
    try:
        payload = json.loads(raw)
    except Exception as e:
        log(f"json parse failed: {e!r}")
        return

    file_path = str(payload.get("file_path", ""))
    log(f"file_path={file_path}")
    if not file_path.endswith(".py") or not Path(file_path).is_file():
        log("skip: not an existing .py file")
        return

    for label, args in (
        ("check", [sys.executable, "-m", "ruff", "check", "--fix", file_path]),
        ("format", [sys.executable, "-m", "ruff", "format", file_path]),
    ):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
            log(f"ran {label}: exit={r.returncode} err={r.stderr.strip()[:300]}")
        except Exception as e:
            log(f"ruff {label} failed: {e!r}")


if __name__ == "__main__":
    main()
