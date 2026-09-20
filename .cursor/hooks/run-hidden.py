#!/usr/bin/env python3
"""run-hidden: launch a console command with NO visible console window (Windows).

Use it to wrap any direct-command hook entry in .cursor/hooks.json (the design
detector, Semgrep, a linter) so the child process cannot pop a terminal window on
the user's desktop. On non-Windows it is a transparent pass-through.

  <python.exe> .cursor/hooks/run-hidden.py <command> [args...]

- stdin (the hook's JSON payload) is inherited by the child unchanged.
- stdout / stderr / exit code are relayed unchanged, so hook semantics are kept.
- A .cmd/.bat executable (npx, semgrep shims) is run via cmd.exe /d /c, hidden.
- Never use this for a process the user is meant to watch or interact with.

ASCII-only on purpose (cp1252 consoles).
"""
import os
import shutil
import subprocess
import sys

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def resolve(argv):
    """Turn a .cmd/.bat launcher into a cmd.exe invocation so CreateProcess can run it."""
    if sys.platform != "win32" or not argv:
        return argv
    exe = argv[0]
    found = shutil.which(exe) or exe
    if found.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/c", found] + argv[1:]
    return [found] + argv[1:] if found != exe else argv


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        sys.stderr.write("run-hidden: no command given\n")
        return 2
    # stdin is inherited, not pre-read: the child reads the hook payload exactly as it
    # would have, and the wrapper never blocks on a pipe that has no writer.
    try:
        proc = subprocess.run(
            resolve(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=NO_WINDOW,
        )
    except FileNotFoundError as e:
        sys.stderr.write("run-hidden: cannot start %s (%s)\n" % (argv[0], e))
        return 127
    sys.stdout.buffer.write(proc.stdout)
    sys.stderr.buffer.write(proc.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
