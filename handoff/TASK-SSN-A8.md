# TASK-SSN-A8 — Wire the owner-pool root into runs + withhold deactivated owner assets

A4 added `ContextPaths.library_owner_pool` and the `ctx.library` facade reads/grant-filters it, but the supervisor never populates that field, so at run time it is always `None` and the whole owner-pool grant path is dead code. Also, the facade's `get()`/`path()` return a DEACTIVATED owner asset (no status filter), inconsistent with `find()` (active-only) and with "remove == hide from selection". Fix both. Make the two supervisor-authored frozen tests green WITHOUT editing them:
- `tests/core/test_supervisor_library_owner_pool.py` (real run's context.json must carry `paths.library_owner_pool` == `<library_dir>/_owner`).
- `tests/sdk/test_ctx_library_grants.py::test_deactivated_granted_owner_asset_is_withheld_from_workflows`.

Keep every other existing test green (do NOT edit any test).

## Part 1 — supervisor wiring (`app/core/supervisor.py`)

The app's Library-tab endpoints store owner assets under `<library_dir>/_owner` (`app/api/library.py::_owner_root` = `_library_dir(request) / "_owner"`). The supervisor must compute the SAME root and thread it into every run's context so `ctx.library` sees the owner pool.

- Add a field `library_owner_pool_root: Path | None = None` to the `_ContextWiring` dataclass (near `library_root`, ~line 104).
- In `run_request` (where `library_root` is computed, ~line 471), compute `library_owner_pool_root = ((library_dir or LIBRARY_DIR) / "_owner").resolve()` and pass it into `_ContextWiring(...)` (~line 482-498). Compute it unconditionally (dry AND real) — it is a read-only durable store the owner populates via the app; do NOT `mkdir` it (the facade/LibraryStore tolerate a missing owner pool, and a dry run must not create real-library state). Use the module-level `LIBRARY_DIR` default exactly as `library_root` does, so the supervisor root matches the app root.
- In the `ContextPaths(...)` construction (~line 282-291, in the ContextFile builder), set `library_owner_pool=wiring.library_owner_pool_root` alongside the existing `library=` / `library_overlay=` lines.

Confirm `ContextPaths` already has the `library_owner_pool` field (added in A4) and that it serialises into context.json by that name (the other paths already do).

## Part 2 — withhold deactivated owner assets (`sdk/sfvf/context.py`)

In the `Library` facade's `_granted_owner_asset(self, name_or_id)` (~line 387-395), after resolving `owner_asset = self._owner_pool.get(name_or_id)` and before/with the grant check, treat a non-active asset as absent: if `owner_asset.status != "active"`, return `None`. This makes `get()` and `path()` (both of which route through `_granted_owner_asset`) consistent with `find()`'s active-only default. Do not change `find()` (it already passes `status="active"` to the owner pool). Do not change own-namespace resolution.

## Scope

- app/core/supervisor.py
- sdk/sfvf/context.py

Do NOT modify: any test, `app/api/`, `frontend/`, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/core/test_supervisor_library_owner_pool.py tests/sdk/test_ctx_library_grants.py tests/sdk/test_ctx_library.py tests/sdk/test_ctx_library_hardening.py tests/core/test_supervisor.py -q` passes (the two new frozen tests included), only the known pre-existing unrelated failures elsewhere.
- `./.venv/Scripts/python.exe -m ruff check app/core/supervisor.py sdk/sfvf/context.py` and project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary; confirm no other behaviour changed.
