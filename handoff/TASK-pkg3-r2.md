# TASK-pkg3-r2 — two robustness fixes to install.ps1 (Review B)

Cross-family Review B rejected the first cut with two real defects. Fix ONLY `install.ps1` (nothing else). Keep it ASCII-only. `scripts/install-check.ps1` must still print `PASS` (it does on a machine with Python 3.12; do not regress the happy path).

## Fix 1 — `Find-PythonExe` must not throw when a candidate writes to stderr

Under `$ErrorActionPreference = 'Stop'`, a native command whose stderr is redirected with `2>&1` raises a terminating `NativeCommandError` in Windows PowerShell 5.1. So on a machine that HAS the `py` launcher but does NOT have Python 3.12, `& py -3.12 --version 2>&1` throws — which escapes `Find-PythonExe` (it has no guard), propagates to the outer `try/catch`, and the installer dies with a stray error instead of falling through to `python` and then to the clean "Missing prerequisites … winget install Python.Python.3.12" message.

Fix: make each candidate probe in `Find-PythonExe` non-throwing so a failing/absent interpreter is simply skipped. Wrap the `--version` and `-c "import sys; print(sys.executable)"` invocations for each candidate in `try { … } catch { continue }` (and/or run them under a locally scoped `$ErrorActionPreference = 'Continue'`). The required behaviour: with the `py` launcher present but 3.12 absent, `Find-PythonExe` returns `$null` (no throw), and `Test-Prerequisites` then prints the missing-Python guidance and `exit 1`. A machine WITH a suitable interpreter still resolves it exactly as now.

## Fix 2 — `Add-UserPath` must match PATH entries exactly, not by substring

`Add-UserPath`'s idempotency guard uses `$userPath -like "*$Entry*"`, a wildcard substring test. That both treats `$Entry` as a glob and returns true when a DIFFERENT entry merely contains `$Entry` as a substring (e.g. an unrelated `…\SFVF\bin-old`), so the real launcher `…\Programs\SFVF\bin` would never be added. Make it a segment-exact check mirroring `Remove-UserPath`: split the user PATH on `;`, trailing-`\`-normalize, compare case-insensitively (`-ieq`) against `$Entry`, and add the entry only when no segment matches. Re-adding must stay idempotent (no duplicate).

## Done when

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-check.ps1` still prints `PASS` (the supervisor re-runs it locally).
- `install.ps1` is ASCII-only; no other file changed; the Python suite/ruff/mypy are unaffected (no `.py` touched).

## Builder notes

Record any tooling friction / defect learning in `docs/BUILDER_NOTES.md`.
