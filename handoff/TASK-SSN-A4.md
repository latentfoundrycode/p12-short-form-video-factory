# TASK-SSN-A4 — ctx.library reads the granted owner pool (two-root, grant-aware facade)

Make a workflow's `ctx.library` see its OWN namespace assets PLUS owner-pool assets granted to it, and add a blob-path accessor. Pinned by `tests/sdk/test_ctx_library_grants.py` (make it green without editing it). All changes in `sdk/sfvf/context.py`.

## Background (already built, reuse)

- `sfvf.library.LibraryStore(root)` — content-addressed store; `find(status=...)`, `get(name_or_id)`, `blob_path(id)`.
- `sfvf.grants.GrantStore(owner_root)` — `get_grant(id)` / `grant_allows(id, workflow_id)` (default-deny; fail-closed).
- The `Library` facade in `context.py` today is SINGLE-root (its own namespace `paths.library`, plus a dry-run overlay). `ctx.workflow_id` is available (`context.py` ~483).

## What to implement

1. **`ContextPaths` gains a field** (`context.py`): `library_owner_pool: Path | None = Field(default=None, description="The shared owner-uploaded asset pool (library/_owner); read-only to a workflow.")`.

2. **The `Library` facade becomes two-root, grant-aware** (in `Library` + its construction in `_make_library`):
   - When `paths.library_owner_pool` is set, the facade also holds a READ-ONLY owner-pool `LibraryStore(owner_pool_root)` and a `GrantStore(owner_pool_root)`, and knows `ctx.workflow_id`.
   - An owner-pool asset is VISIBLE to this workflow only when `GrantStore.grant_allows(asset_id, ctx.workflow_id)` is True.
   - `find(...)`: return own-namespace results (as today, including the dry-run overlay) UNION the owner-pool results filtered by the grant check. OWN-NAMESPACE PRECEDENCE: if an id appears in both roots (same content hash), keep the own-namespace one; never duplicate an id. Fold the owner-pool source in AFTER the existing overlay/real dedup.
   - `get(name_or_id)`: resolve in the own namespace first (overlay + real, as today); if not found there, resolve in the owner pool but return it ONLY if granted (else None).
   - **New method `path(self, name_or_id: str) -> Path | None`**: return the on-disk blob path of a resolvable asset — own namespace first (its `blob_path`), else a GRANTED owner-pool asset's `blob_path`, else None. This is the read a workflow uses to hand a music/voice file to the mixer.
   - **Writes stay own-namespace-only**: `put` / `annotate` continue to go to the workflow's own namespace (or the dry-run overlay). NEVER route a write to the owner-pool store — construct it read-only (do not call put/annotate/deactivate on it). A workflow cannot widen its own access.

3. **Wire it up** in `_make_library` (or wherever the facade is constructed): pass the owner-pool root (`paths.library_owner_pool`) and `workflow_id` through. When `paths.library_owner_pool` is None (workflows with no owner pool, existing behaviour), the facade behaves exactly as today (single-root) — do not regress the existing `tests/sdk/test_ctx_library*.py`.

Keep the merge deterministic and consistent with the existing facade code. Import `GrantStore` from `.grants`.

## Scope

- `sdk/sfvf/context.py`

Touch nothing else. Do NOT modify any test, other SDK files, `docs/`, `handoff/`, `.env`, `secrets/`, or CI. Do NOT add dependencies.

## Constraints

- Workspace boundary; ASCII; one paragraph is one line.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_ctx_library_grants.py -q` passes (7).
- No regression across the SDK library tests: `./.venv/Scripts/python.exe -m pytest tests/sdk -q`.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/context.py` and `./.venv/Scripts/python.exe -m mypy sdk/sfvf/context.py` are clean.
- Print the files you changed and a one-paragraph summary.
