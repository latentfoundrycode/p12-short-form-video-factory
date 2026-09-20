#!/usr/bin/env python3
"""Workspace-boundary detector for the Cursor afterFileEdit hook (advisory).

Reads the hook's JSON from stdin, takes the edited file's path and the workspace
root(s), and records any edit that landed OUTSIDE the workspace to
<workspace>/docs/BOUNDARY_VIOLATIONS.md. The supervisor reads that file at
step 4 (Inspect) of the delegation loop and treats an entry like SCOPE DRIFT.

This hook runs AFTER the edit, so it cannot prevent it - it detects. Always
exits 0 (advisory; never fail-closed). ASCII-only on purpose (cp1252 consoles).
"""
import json
import os
import sys
import time


def norm(p):
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def inside(path, root):
    path = norm(path)
    root = norm(root).rstrip("\\/")
    return path == root or path.startswith(root + os.sep)


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    roots = data.get("workspace_roots") or [os.getcwd()]
    if isinstance(roots, str):
        roots = [roots]
    file_path = data.get("file_path") or data.get("path") or ""
    if not file_path:
        return 0

    if any(inside(file_path, r) for r in roots):
        return 0

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = "- %s  OUTSIDE WORKSPACE: %s  (roots: %s)\n" % (
        stamp, os.path.abspath(file_path), "; ".join(os.path.abspath(r) for r in roots))
    log_dir = os.path.join(roots[0], "docs")
    log = os.path.join(log_dir, "BOUNDARY_VIOLATIONS.md")
    try:
        os.makedirs(log_dir, exist_ok=True)
        new = not os.path.exists(log)
        with open(log, "a", encoding="utf-8") as f:
            if new:
                f.write("# Workspace boundary violations\n\n"
                        "Edits the builder made outside the Workspace, recorded by the "
                        "boundary-check hook. Each entry is handled like SCOPE DRIFT.\n\n")
            f.write(line)
    except Exception as e:
        sys.stderr.write("boundary-check: could not write log: %s\n" % e)
    sys.stderr.write("boundary-check: " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
