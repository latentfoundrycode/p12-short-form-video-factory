#!/usr/bin/env python
"""Cursor afterFileEdit hook: lint-fix and format edited Python files with ruff.

Reads stdin as bytes and decodes utf-8-sig, because Windows Cursor prefixes the
payload with a UTF-8 BOM. Uses sys.executable (the venv python Cursor launched
this hook with). Never raises, so it can't block the agent.
"""
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception:
        return

    file_path = str(payload.get("file_path", ""))
    if not file_path.endswith(".py") or not Path(file_path).is_file():
        return

    for args in (
        [sys.executable, "-m", "ruff", "check", "--fix", file_path],
        [sys.executable, "-m", "ruff", "format", file_path],
    ):
        try:
            subprocess.run(args, capture_output=True, text=True, timeout=60)
        except Exception:
            pass


if __name__ == "__main__":
    main()
