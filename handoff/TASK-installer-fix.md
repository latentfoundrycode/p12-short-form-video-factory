# TASK-installer-fix — installer robustness (always npm ci) + install_report.txt

A change cycle on the finished project. Two fixes to the installer, in `install.ps1` and `install.cmd` ONLY. Keep both files ASCII-only (Windows PowerShell 5.1 mis-parses non-ASCII without a BOM). The frozen contract is `scripts/install-check.ps1` (updated) — it must print `PASS`.

## Fix 1 — always run `npm ci` before the frontend build (the actual install failure)

Real-world symptom: a fresh `install.cmd` failed at "Building the frontend" with `tsc -b` errors like `Cannot find module '@testing-library/react' | 'vitest'` — the build typechecks the test files, which import dev-dependencies (`vitest`, `@testing-library/*`) that were **not present** in the machine's `frontend/node_modules`.

Cause: `install.ps1` runs `npm ci` only when `frontend/node_modules` is ABSENT. A **stale/incomplete** `node_modules` (present but not matching `package-lock.json`) is used as-is, so the build runs against incomplete dependencies and fails.

Fix: run `npm ci` **unconditionally** before `npm --prefix frontend run build` — remove the "only if `node_modules` is missing" guard. `npm ci` deletes `node_modules` and installs exactly from `package-lock.json` (including dev-dependencies), which is the deterministic, correct behaviour for an installer and guarantees the build has everything it needs. Keep a clear failure message if `npm ci` itself fails (missing lockfile, network, etc.).

## Fix 2 — write `install_report.txt` and stop the window vanishing

When `install.cmd` is double-clicked and fails, the console window closes immediately, so the owner cannot read or copy the error. Fix both the record and the window:

### `install.ps1`

- Write a full per-run transcript to **`<RepoRoot>\install_report.txt`** (i.e. next to `install.cmd`; `<RepoRoot>` is `$PSScriptRoot`). Use `Start-Transcript -Path <report> -Force` near the very start (right after `$RepoRoot`/paths are computed, before prerequisite checks) and `Stop-Transcript` in a `finally` on the outermost try so the transcript is always closed — on success, on a handled failure, and on an unhandled throw. The transcript must capture the whole run, including the npm/pip output and the final outcome.
- Before `Stop-Transcript`, print a clear final status line the owner (and you) can grep: `SFVF install: SUCCESS` or `SFVF install: FAILED - <reason>`. The existing `catch { Write-Host $_; exit 1 }` should set the FAILED line; the success path the SUCCESS line.
- Guard `Start-Transcript`/`Stop-Transcript` so a transcript problem never itself aborts the install (wrap in try/catch where sensible); the install must still work if transcription is somehow unavailable.
- Do not change the install/uninstall logic other than Fix 1 and this transcript wrapper.

### `install.cmd`

Keep the window open and preserve the exit code, e.g.:

```bat
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "SFVF_EC=%ERRORLEVEL%"
echo.
echo (A full log was written to install_report.txt in this folder.)
pause
exit /b %SFVF_EC%
```

`uninstall.cmd` may keep its current form (uninstall is quick and low-risk); only add the `pause` there too if trivial.

## Constraints

- `install.ps1` and `install.cmd` ASCII-only; no other file changed (the contract `scripts/install-check.ps1`, `.gitignore`, and this brief are already handled by the supervisor).
- `npm ci` unconditional is the fix — do not merely re-run `npm install`, and do not delete `node_modules` yourself; `npm ci` does that correctly.
- `install_report.txt` is written to `<RepoRoot>` on every run (it is git-ignored).
- One paragraph is one line in any Markdown you write.

## Done when

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-check.ps1` prints `PASS` (it now also asserts `install_report.txt` was written). The supervisor runs this locally.
- A real `install.cmd` on a machine whose `frontend/node_modules` is stale/incomplete now succeeds (npm ci repopulates it) and leaves an `install_report.txt`.
- The Python suite/ruff/mypy are unaffected (no `.py` changed).

## Builder notes

Record any tooling friction / defect learning in `docs/BUILDER_NOTES.md`.
