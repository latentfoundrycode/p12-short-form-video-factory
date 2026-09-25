# TASK-SSN-A8-r2 — Narrow the owner-asset status filter + never create the owner pool on read

The A8 supervisor wiring is accepted. Two defects in the `ctx.library` facade (`sdk/sfvf/context.py`) remain, both found by cross-family Review B. Fix ONLY `sdk/sfvf/context.py`. Make the supervisor-authored frozen tests green without editing them:
- `tests/sdk/test_ctx_library_grants.py::test_deactivated_granted_owner_asset_is_withheld_from_workflows` (already passing, keep it green)
- `tests/sdk/test_ctx_library_grants.py::test_superseded_granted_owner_asset_still_resolves_by_id` (currently RED)
- `tests/sdk/test_ctx_library_grants.py::test_read_does_not_create_missing_owner_pool` (currently RED)

Keep every other existing test green (do NOT edit any test).

## Defect 1 — status filter is too wide

`_granted_owner_asset` (~line 387-395) currently does `if owner_asset.status != "active": return None`, which withholds not just deactivated (`inactive`) assets but also `superseded` and `rejected` ones. Per SDK section 7.7 a recorded asset id must still resolve even after it is superseded — and own-namespace `get()`/`path()` already do resolve those. Only the deactivate action (which sets status `inactive`) should hide an asset from selection.

- Change the check to withhold ONLY the `inactive` status: `if owner_asset.status == "inactive": return None`. Leave the grant check after it unchanged. `find()` is unchanged (it already passes `status="active"` to the owner pool for listing; that is the correct listing default and is separate from id-resolution).

## Defect 2 — a read creates the owner pool on disk

Now that the supervisor sets `paths.library_owner_pool` on every run (dry and real), `ctx.library.find()` calls `LibraryStore.find` on the owner-pool root; when that root has no catalog yet (the owner has uploaded nothing), the rebuild path writes `library/_owner/catalog.json`, so a dry run creates real-library state (violates section 7.9). The owner pool must be created ONLY by the app (owner upload), never by a workflow read.

- Guard the owner-pool reads on the root EXISTING on disk, checked lazily at read time (NOT at facade construction — the owner pool may be created by the app after the facade is built, and tests construct the context before seeding). Concretely: store the owner-pool root path on the facade in `__init__` (keep constructing `_owner_pool`/`_grants` as now when the root is not None), and treat the owner pool as absent for reads when the root does not exist. A small helper such as `_owner_pool_ready(self) -> bool` returning `self._owner_pool is not None and self._grants is not None and self._owner_pool_root is not None and self._owner_pool_root.exists()` is a clean way; use it to short-circuit BOTH `find()` (return own-only) and `_granted_owner_asset()` (return None) before any owner-pool call. Do not create the directory anywhere in the facade.

Do not change own-namespace resolution, the dry-run overlay, `put`/`_write_store`, or the supervisor wiring.

## Scope

- sdk/sfvf/context.py

Do NOT modify: any test, `app/`, `frontend/`, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_ctx_library_grants.py tests/sdk/test_ctx_library.py tests/sdk/test_ctx_library_hardening.py tests/core/test_supervisor_library_owner_pool.py tests/core/test_supervisor.py -q` passes (all three named cases included), only the known pre-existing unrelated failures elsewhere.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/context.py` and project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary; confirm no other behaviour changed.
