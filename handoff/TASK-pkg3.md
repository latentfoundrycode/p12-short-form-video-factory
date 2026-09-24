# TASK-pkg3 — the SFVF installer (install.ps1 + install.cmd + uninstall.cmd)

## Goal

Give SFVF a per-user, no-admin Windows installer for a local server (Delivery-Conventions §3). The owner double-clicks `install.cmd`; afterwards `sfvf` is on PATH and starts the server. Runtime data lives outside the install folder (via `SFVF_DATA_DIR`, PKG-2) so upgrades never wipe it. The frozen contract is `scripts/install-check.ps1` — read it; your scripts must make it print `PASS`.

## Files to create (repo root)

1. `install.ps1` — all the logic.
2. `install.cmd` — double-clickable wrapper: `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*`.
3. `uninstall.cmd` — wrapper: `... "%~dp0install.ps1" -Uninstall %*`.

Do not touch any test or other file. `install-check.ps1` (the contract) and `VERSION` already exist.

## Fixed paths / identifiers (install-check.ps1 depends on these EXACTLY)

- Install dir: `$env:LOCALAPPDATA\Programs\SFVF`
- Data dir: `$env:LOCALAPPDATA\SFVF` (created via the `SFVF_DATA_DIR` the launcher sets; never inside the install dir)
- Launcher: `<InstallDir>\bin\sfvf.cmd`, and `<InstallDir>\bin` is added to the **user** PATH (`[Environment]::…('Path','User')`)
- Registry (Apps & features): `HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SFVF` with `DisplayName`, `DisplayVersion` (= the `VERSION` file, stripped), `Publisher`, `InstallLocation`, `UninstallString`, `NoModify=1`, `NoRepair=1`
- Version: read `VERSION` at the repo root, stripped.

## `install.ps1` — parameters and flow

`param([switch]$Silent, [switch]$Uninstall, [switch]$RemoveData)`, `$ErrorActionPreference='Stop'`.

### Install (default)

1. **Prerequisites** — check and, if missing, print exactly what to install (via `winget`) and exit non-zero (even under `-Silent`): Python **3.12.4+** (find a suitable interpreter — `py -3.12` or `python`; parse `--version` and compare), `ffmpeg` and `ffprobe` on PATH, and `npm`/Node (needed for the frontend build below). Do not half-install.
2. **Already installed** — if the registry key exists: under `-Silent`, proceed as an in-place upgrade; interactively, show a 3-way prompt (Upgrade/reinstall — keeps data · Uninstall · Cancel) and act accordingly.
3. **Build the frontend** — run `npm --prefix frontend run build` from the repo (writes `app/web/`). Fail with a clear message if it errors.
4. **Assemble the install dir** — create `<InstallDir>`; copy the runtime tree into it: `app/` (incl. the built `app/web/`), `sdk/`, `workflows/`, `rules/`, `skills/`, `assets/`, `VERSION`, `requirements.txt`, `install.ps1` (so the registered uninstaller can run). Do NOT copy `frontend/`, `tests/`, `.git/`, `venvs/`, `runs/`, `cache/`, `library/`, `.venv/`, `node_modules/`, or `__pycache__`. On upgrade, replace program files but never touch the data dir.
5. **Build the isolated venv** — `python -m venv <InstallDir>\.venv`, then `<InstallDir>\.venv\Scripts\python.exe -m pip install -r requirements.txt` **with the working directory set to `<InstallDir>`** so the `-e ./sdk` line resolves to `<InstallDir>\sdk`.
6. **Launcher** — write `<InstallDir>\bin\sfvf.cmd` that sets `SFVF_DATA_DIR=%LOCALAPPDATA%\SFVF` and `PYTHONPATH=<InstallDir>` and runs `"<InstallDir>\.venv\Scripts\python.exe" -m app.serve %*`. It must NOT permanently `cd` the caller's shell (use the env/PYTHONPATH approach, not a bare `cd`). Then add `<InstallDir>\bin` to the user PATH if not already present.
7. **Registry + installed.json** — write the Apps & features key (fields above; `UninstallString` = `powershell -NoProfile -ExecutionPolicy Bypass -File "<InstallDir>\install.ps1" -Uninstall`), and write `<InstallDir>\installed.json` `{version, installed_utc, location}`.
8. Print a short success line (unless `-Silent`).

### Uninstall (`-Uninstall`)

1. Remove `<InstallDir>\bin` from the user PATH.
2. Remove the registry key.
3. Remove `<InstallDir>` entirely (program files + venv).
4. **Keep the data dir** (`$env:LOCALAPPDATA\SFVF`) UNLESS `-RemoveData` is passed (interactively you may ask; under `-Silent` without `-RemoveData`, always keep it).
5. Exit 0 even if some pieces were already absent (idempotent).

## Constraints

- Per-user only — no admin/elevation, no `HKLM`, no `%ProgramFiles%`.
- Reversible and idempotent: a second install upgrades in place; uninstall then re-install works; nothing is left on PATH/registry after uninstall.
- `install-check.ps1` must print `PASS` (it drives `install.ps1 -Silent`, checks files/launcher/PATH/version/registry, a data marker surviving upgrade, and uninstall keeping data).
- No new Python dependency; PowerShell 5.1-compatible (the owner's default shell). One paragraph is one line in any Markdown you write.

## Done when

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-check.ps1` prints `PASS` (the supervisor runs this locally — Installer verification: local).
- The existing Python suite is unaffected (no `.py` changed): `.\.venv\Scripts\python.exe -m pytest -q`, ruff, mypy stay green.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for Bridge Feedback; record any defect/pitfall learning there too, for the Issues file.
