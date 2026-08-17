#!/usr/bin/env python
"""Cursor afterFileEdit hook: format edited frontend files with Prettier.

Reads stdin as bytes and decodes utf-8-sig, because Windows Cursor prefixes the
payload with a UTF-8 BOM. Never raises, so it can't block the agent. No-ops
unless the edited file is under frontend/ and ends .ts, .tsx, or .css.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception:
        return

    raw = Path(str(payload.get("file_path", "")))
    path = raw if raw.is_absolute() else Path.cwd() / raw
    if not path.is_file() or path.suffix not in {".ts", ".tsx", ".css"}:
        return

    try:
        relative = path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return
    if not relative.parts or relative.parts[0] != "frontend":
        return

    node = shutil.which("node")
    prettier = Path.cwd() / "frontend" / "node_modules" / "prettier" / "bin" / "prettier.cjs"
    if node is None or not prettier.is_file():
        return

    try:
        subprocess.run(
            [node, str(prettier), "--write", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
