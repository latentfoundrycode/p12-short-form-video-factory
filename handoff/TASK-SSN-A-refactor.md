# TASK-SSN-A-refactor — Stage-A behaviour-preserving cleanup

Two small, behaviour-preserving extractions in the SDK. This is a refactoring pass: NO behaviour change, NO new features, NO API signature changes, NO fixes to logged HARDENING items. The existing tests are the safety net and MUST stay green unchanged — do NOT edit any test.

## 1. Extract the single-entry catalog refresh in `sdk/sfvf/library.py`

`_set_asset_status` (added in A1, ~lines 447-455) and `_apply_supersession` (pre-existing, ~lines 525-532) contain the identical block: after the sidecar is written, "read the catalog; if it is missing or the id is absent, call `rebuild_catalog()`; otherwise overwrite just that one entry via `_entry_from_asset` (preserving its existing `novel_facets`) and `_write_json_atomic`".

- Add a private helper `_refresh_catalog_entry(self, asset: Asset) -> None` holding that block, and call it from both methods in place of the inline code. Preserve the exact current behaviour of BOTH call sites, including the `novel_facets` preservation. If the two blocks differ in any detail, STOP and do not merge — report the difference instead.

## 2. Extract granted-owner-asset resolution in `sdk/sfvf/context.py`

The `Library` facade's `get()` (~lines 371-383, owner-pool tail) and `path()` (~lines 385-401, owner-pool tail) both repeat: "if `self._owner_pool is None or self._grants is None`: return None; `owner_asset = self._owner_pool.get(name_or_id)`; if None return None; if `grant_allows(owner_asset.id, ctx.workflow_id)` return the asset (or its blob path); else None". Only the returned value differs (the `Asset` vs its blob path).

- Add a private helper `_granted_owner_asset(self, name_or_id) -> Asset | None` returning the granted owner `Asset` (or None). Rewrite `get()`'s owner tail to use it, and `path()`'s owner tail to call it and return the blob path of the returned asset. Keep the public `get`/`path`/`find` signatures and behaviour identical. Leave `find()`'s owner-pool filter AS-IS (do not merge it — its shape differs).

## Scope

- sdk/sfvf/library.py
- sdk/sfvf/context.py

Do NOT modify: any test, `app/`, `frontend/`, `docs/`, `handoff/`, dependencies.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk -q` passes with NO test changes (the catalog/grant tests are the safety net); the only acceptable failures elsewhere are the two pre-existing unrelated ones.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/library.py sdk/sfvf/context.py` and project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary; confirm no behaviour changed.
