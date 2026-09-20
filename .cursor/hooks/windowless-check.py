#!/usr/bin/env python3
"""windowless-check: flag console subprocess launches that would pop a terminal
window on Windows.

Scans hook scripts and agent tooling (default: .cursor/hooks) plus any extra paths
given, and reports every Python subprocess.* / os.system / os.popen call and every
Node child_process spawn/exec call that does not carry the windowless flag:

  Python : creationflags=subprocess.CREATE_NO_WINDOW   (0 on non-Windows)
  Node   : { windowsHide: true }

A call may be exempted with a comment on the same line or the line above:

  # windowless: visible-ok <reason the window serves the user>
  // windowless: visible-ok <reason>

Signal caveat: a call that sets CREATE_NEW_PROCESS_GROUP (a CTRL_BREAK stop path)
is reported as NOTE, not FAIL, when it lacks CREATE_NO_WINDOW - hiding it must be
verified against the stop path, not flipped blindly.

Exit 0 = clean (NOTEs allowed), 1 = at least one FAIL, 2 = nothing scanned.
Usage: python windowless-check.py [path ...]
ASCII-only on purpose (cp1252 consoles).
"""
import os
import re
import sys

PY_EXT = (".py",)
JS_EXT = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")
SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "dist", "build", "__pycache__"}

PY_CALL = re.compile(r"\b(subprocess\.(?:run|Popen|call|check_call|check_output)|os\.system|os\.popen)\s*\(")
JS_CALL = re.compile(r"\b(spawn|spawnSync|exec|execSync|execFile|execFileSync)\s*\(")
EXEMPT = re.compile(r"windowless:\s*visible-ok\b")


def call_text(src, open_paren):
    """Return the text of the call from the opening paren to its matching close."""
    depth = 0
    i = open_paren
    in_str = None
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ("'", '"', "`"):
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return src[open_paren:i + 1]
        i += 1
    return src[open_paren:]


def line_of(src, pos):
    return src.count("\n", 0, pos) + 1


def exempted(lines, lineno):
    """Same line: any trailing comment. Line above: only a comment-only line, so a
    trailing comment on the previous statement never exempts this one."""
    if 1 <= lineno <= len(lines) and EXEMPT.search(lines[lineno - 1]):
        return True
    if lineno >= 2:
        above = lines[lineno - 2].strip()
        if above.startswith(("#", "//")) and EXEMPT.search(above):
            return True
    return False


def scan_file(path):
    findings = []
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return findings
    lines = src.split("\n")
    is_py = path.endswith(PY_EXT)
    pattern = PY_CALL if is_py else JS_CALL
    for m in pattern.finditer(src):
        name = m.group(1)
        ln = line_of(src, m.start())
        if exempted(lines, ln):
            continue
        body = call_text(src, m.end() - 1)
        if is_py:
            if name in ("os.system", "os.popen"):
                findings.append(("FAIL", path, ln, name, "cannot be made windowless; use subprocess.run with creationflags"))
                continue
            if "creationflags" in body and "NO_WINDOW" in body:
                continue
            if "creationflags" in body and "CREATE_NEW_PROCESS_GROUP" in body:
                findings.append(("NOTE", path, ln, name, "process-group spawn without CREATE_NO_WINDOW; verify the stop path before hiding"))
                continue
            findings.append(("FAIL", path, ln, name, "missing creationflags=NO_WINDOW"))
        else:
            if "windowsHide" in body:
                continue
            findings.append(("FAIL", path, ln, name, "missing windowsHide: true"))
    return findings


def main():
    paths = sys.argv[1:] or [".cursor/hooks"]
    files = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
            continue
        for root, dirs, names in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for n in names:
                if n.endswith(PY_EXT + JS_EXT):
                    files.append(os.path.join(root, n))
    if not files:
        print("windowless-check: nothing to scan under %s" % ", ".join(paths))
        return 2
    findings = []
    for f in sorted(files):
        findings.extend(scan_file(f))
    fails = [f for f in findings if f[0] == "FAIL"]
    for kind, path, ln, name, why in findings:
        print("%s  %s:%d  %s(...)  %s" % (kind, path.replace("\\", "/"), ln, name, why))
    print("windowless-check: %d file(s) scanned, %d FAIL, %d NOTE" % (len(files), len(fails), len(findings) - len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
