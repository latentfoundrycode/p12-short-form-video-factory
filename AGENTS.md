# SFVF

Short-Form Video Factory is a single-user local app that runs pluggable workflows to generate video. SFVF itself produces no videos; it finds, configures, runs, pays for, records, and improves those workflows. The default format is short-form vertical video; the format is a workflow's declaration, not a property of the chassis.

## Directories

- `app/` — Python backend (API, supervisor, registry, learning); `app/web/` is the built frontend.
- `sdk/` — library installed into every workflow environment.
- `workflows/` — plug-ins; never written to while running.
- `rules/` — runtime instructions consumed by workflow agents during video generation; not coding-agent instructions (those are `.cursor/rules/` and `AGENTS.md`). Edited by hand only.
- `skills/` — on-demand runtime reference consumed by workflow agents during video generation; not coding-agent instructions (those are `.cursor/rules/` and `AGENTS.md`).
- `assets/` — bundled openly-licensed fonts.
- `docs/` — authoritative specifications.
- `frontend/` — React source, built into `app/web/`.
- `tools/` — repo-local check scripts.
- `runs/` — all run output. Runtime-generated; do not create or edit by hand.
- `cache/` — derived step results reusable across runs. Runtime-generated; do not create or edit by hand.
- `library/` — authored reusable assets that outlive runs. Runtime-generated; do not create or edit by hand.
- `venvs/` — one isolated environment per workflow. Runtime-generated; do not create or edit by hand.
- `archive/` — previous versions of edited rules and skills. Runtime-generated; do not create or edit by hand.

## Verification commands

Python commands require `.venv\Scripts\Activate.ps1` first.

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
```

This environment is Windows with PowerShell. POSIX shell syntax will fail.

## Build and run

```
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Build writes into `app/web/`. Uvicorn then serves the API and that SPA as one process. Use `npm --prefix frontend run dev` (Vite proxy to `:8000`) while iterating on the frontend.

## Specifications

`docs/` is authoritative:

- `docs/SFVF_Project_Requirement_Document.md` — what SFVF should do
- `docs/SFVF_Architecture.md` — how to build it
- `docs/SFVF_Workflow_SDK.md` — how to write workflow plug-ins
