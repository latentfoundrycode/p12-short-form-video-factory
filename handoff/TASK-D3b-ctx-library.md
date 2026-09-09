# TASK D-3b — ctx.library facade + novelty event + dry-run overlay (SDK §7)

## Goal (one sentence)
Implement the `Library` facade in `sdk/sfvf/context.py` so a workflow uses `ctx.library` to read/write
the durable asset store, with a novelty `library` event and a dry-run overlay that never mutates the
real library.

## Frozen contract (already committed — do NOT edit any test)
`tests/sdk/test_ctx_library.py`. Frozen: `Library.find/get/value/describe/put/annotate` signatures,
`ContextPaths.library`/`library_overlay`, `ContextFile.library_facets`, `LibraryFacetDecl`, and
`Context.library` (None when no `paths.library`). All existing SDK tests must stay green. Only
`sdk/sfvf/context.py` should change.

## Design
`Library.__init__` already stores `self._ctx`, `self._facets` (a tuple of `FacetSpec`),
`self._real_root`, and `self._overlay_root` (set only in a dry run). Build stores lazily/eagerly:
- `self._real = LibraryStore(self._real_root, facets=self._facets)` (import `LibraryStore` from
  `.library` — re-add the import).
- `self._overlay = LibraryStore(self._overlay_root, facets=self._facets)` when `self._overlay_root`
  is not None (i.e. a dry run), else None.

### Reads (overlay layered over real when dry)
- `get(name_or_id)` — if overlay: `overlay.get(...) or real.get(...)`; else `real.get(...)`.
- `value(name_or_id)` — same layering, using `.value(...)`.
- `find(*, tags, facets, status="active")` — real's matches, then overlay's matches layered on top by
  id (an overlay asset with the same id wins), returned sorted by `(created_utc, id)`. When there is
  no overlay, just `real.find(...)`.

### `describe(assets) -> str`
A compact, deterministic text block an agent can read — one entry per asset. Include at least each
asset's id (or a short prefix), its tags, its facets, its description, and its caveats, one asset per
paragraph. Plain text; it must not call any model. (The frozen test only checks the description text
and a facet value appear, so exact layout is yours — keep it readable and stable.)

### `put(name, source, *, kind=None, tags, facets, description, caveats, supersedes, provenance)`
- Choose the write store: `self._overlay if self._overlay is not None else self._real`.
- If `isinstance(source, Path)` → `store.put(name, source, kind=(kind or "file"), ...)`; else treat
  `source` as JSON → `store.put_value(name, source, kind=(kind or "value"), ...)`. Pass tags/facets/
  description/caveats/supersedes/provenance through.
- After the write, emit a `library` event iff the asset introduced a novel open value:
  `novel = store.novel_facets(asset.id)`; if `novel`, `self._ctx.emit({"t": "library", "asset":
  asset.id, "novel": {k: asset.facets[k] for k in novel}})`. Emit nothing when `novel` is empty.
- Return the asset.

### `annotate(asset_id, *, caveats=None, facets=None)`
- Real run: `self._real.annotate(asset_id, caveats=caveats, facets=facets)`.
- Dry run: the change must land in the overlay and NOT touch the real library. If the overlay does not
  already hold the asset, copy-on-write it in first: copy `real_root/items/<id>` → `overlay_root/
  items/<id>` and `real_root/items/<id>.json` → `overlay_root/items/<id>.json` (create dirs;
  `shutil.copyfile`), then `self._overlay.rebuild_catalog()` so the overlay knows it. Then
  `self._overlay.annotate(asset_id, caveats=caveats, facets=facets)`. If the asset is in neither real
  nor overlay, let `annotate` raise `LibraryError` (unknown asset) as usual.

## Constraints / do-nots
- Do NOT edit any test or change a frozen signature; keep all existing SDK tests green.
- Do NOT wire the supervisor / context.json population (that is D-3c) — this increment is the SDK
  facade only, tested by building a `Context` directly.
- No new dependencies (stdlib `shutil` + the existing `sfvf.library` are fine). Keep `ruff`,
  `ruff format`, and `mypy --strict` clean; match the SDK style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_ctx_library.py tests/sdk/test_step.py tests/sdk/test_forecast.py tests/sdk/test_library_store.py tests/sdk/test_library_catalog.py tests/sdk/test_library_mutations.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
