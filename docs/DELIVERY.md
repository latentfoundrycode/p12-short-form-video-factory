# Delivery — how SFVF ships (Delivery-Conventions §3: local server)

SFVF is a **single-user local server**: a FastAPI backend that also serves the built React SPA, run on the owner's own Windows 11 machine and used through a browser at `http://127.0.0.1:8000`. It is not a hosted web app and not a windowed desktop app, so it ships the §3 way — a double-clickable installer that builds an isolated environment, puts a launch command on PATH, and registers an uninstaller — plus a User Manual. This document is the Delivery section the packaging stage builds against.

## Decisions

- **Target:** Windows 11 x64 (the owner's machine). No other platform is a goal.
- **Kind / deliverable:** local server → `install.cmd` + `install.ps1` (+ `uninstall.cmd`), committed at the repo root. No single `.exe` (that is the desktop-app path, §2).
- **Install scope:** per-user, `%LOCALAPPDATA%\Programs\SFVF`, no administrator prompt.
- **Environment:** an isolated venv under the install folder, built **from `requirements.txt`** (the pinned runtime manifest — there is no separate lockfile; the `==` pins are the lock, recorded in `PROJECT_STATUS.md`), with the SDK installed into it. The React frontend is **pre-built** into `app/web/` at package time and shipped as static files, so **Node is not a runtime prerequisite**.
- **Prerequisites the installer checks (and names how to get, via `winget`, if missing):** Python 3.12.4+ (the `>=3.12.4` SDK security floor) and **ffmpeg + ffprobe on PATH** (required by `sfvf._ffmpeg` for finalize/edit). The installer refuses with a plain message rather than a half-install.
- **Launch model:** an **on-demand command**, not a service. `sfvf` starts the server on `127.0.0.1:8000` and opens the browser; a Start-menu shortcut does the same. SFVF is used in creative sessions, not run 24/7, so a background service is not wanted (Delivery §3: a service only when the design needs always-on). Ctrl+C stops it.
- **Data & config location:** `%LOCALAPPDATA%\SFVF` (runs, cache, library, venvs, the SecretStore, `schedules.json`), **never the install folder** — so an upgrade that replaces program files never touches the owner's runs, library, or secrets. In development the same data stays under the repo root (today's behaviour); the location is chosen by an `SFVF_DATA_DIR` environment variable the installer sets, defaulting to the repo root when unset.
- **Already installed → Upgrade / reinstall (keeps data) / Uninstall / Cancel**, the §3 three-way dialog. Upgrade rebuilds the env in place from the new manifest; data and config are untouched. Uninstall removes the env, launcher, PATH entry, and registry entry, and **keeps data** unless the owner opts to remove it. `-Silent` supports both for the lifecycle check.
- **Single version source:** a repo-root `VERSION` file, read by `sfvf --version`, the installer, `installed.json`, and the *Apps & features* entry. First shippable release: `1.0.0`.
- **Command reference:** SFVF gains its first first-party command (`sfvf`), so per §4 it maintains `docs/cli-reference.json` generated from the real command tree, with a CI currency check; every run-sheet/manual command is copied from it.
- **Code signing:** unsigned by default — SmartScreen shows a first-run warning the User Manual explains (More info → Run anyway). A certificate costs money and identity verification; it is the one packaging escalation and is **raised to the owner once**, not assumed. (Owner decision pending; unsigned is the default and does not block building the installer.)

## Verification

`scripts/install-check.ps1` proves the lifecycle silently and reversibly (per-user), following the §3 six steps: precondition (not installed) → install → a **fresh shell** finds `sfvf --version` on PATH and it prints the version → a data marker survives a reinstall → uninstall removes the launcher/PATH/registry entry and keeps the marker → cleanup. It runs where `Installer verification` says (`local`, per `RUN_PARAMETERS.md`).

## Build order (packaging & installer stage — the plan's last stage)

1. **PKG-1** — the `sfvf` launch command (`serve` + `--version` + `--help`), the `VERSION` single source, and `docs/cli-reference.json` + its generator and CI currency check.
2. **PKG-2** — data-root relocation: an `SFVF_DATA_DIR` that moves runs/cache/library/venvs/secrets/schedules out of the install folder (default = repo root in dev, so no behaviour change until set).
3. **PKG-3** — `install.ps1` + `install.cmd` + `uninstall.cmd`: prerequisite checks, the isolated env from `requirements.txt`, the `sfvf` launcher on PATH, `installed.json`, the *Apps & features* entry, the Upgrade/Uninstall/Cancel dialog, `-Silent`.
4. **PKG-4** — `scripts/install-check.ps1` lifecycle verification.
5. **Project end** — final refactoring pass, the User Manual (install + command chapters rendered from the reference), the promotion pass, the deliverable named, `Phase: done`.
