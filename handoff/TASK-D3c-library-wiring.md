# TASK D-3c — supervisor wires ctx.library into every run (§5.10, §7) — closes Stage D

## Goal (one sentence)
Populate each run's context.json with the library namespace root, a per-run dry overlay path, and the
manifest's declared facets, so `ctx.library` is live — and discard a dry run's overlay at the end.

## Frozen contract (already committed — do NOT edit any test)
`tests/core/test_supervisor_library.py` + the `tests/stubs/library_user/` stub. A real run writes under
`library/<namespace>` (namespace "cast") with facets validated (run status `complete`); a dry run
writes to a discarded overlay (real library untouched; no `.library-overlay` left behind). Frozen:
`run_request(..., library_dir=...)`, `_ContextWiring.library_root`/`library_facets`, `LIBRARY_DIR`.

## What to implement

### 1. Compute the library wiring where `cache_root` is computed (in `run_request`)
Just after the `cache_root` block, add (mirroring the cache pattern):
```python
namespace = manifest.library.namespace  # the manifest validator defaults this to the workflow id
library_root = ((library_dir or LIBRARY_DIR) / namespace).resolve()
library_root.mkdir(parents=True, exist_ok=True)
library_facets = [
    LibraryFacetDecl(key=f.key, values=(None if f.values == "open" else list(f.values)))
    for f in manifest.library.facets
]
```
Import `LIBRARY_DIR` from `app.paths` (it is already added). `LibraryFacetDecl` is already imported.
The library is NOT mode-scoped (no dry/real subdir) — it is a durable store shared across runs; the
dry/real distinction is handled by the overlay, not the path.

### 2. Pass them into `_ContextWiring`
Add `library_root=library_root` and `library_facets=library_facets` to the `_ContextWiring(...)`
construction.

### 3. Wire `_make_context` to put them on the context
In `_make_context`, extend the `ContextPaths(...)` with:
- `library=wiring.library_root`
- `library_overlay=(video / ".library-overlay")` — a per-video overlay path. Set it unconditionally;
  the SDK `Library` facade only uses it in a dry run (and fails closed if a dry run lacks it).
And add `library_facets=wiring.library_facets` to the `ContextFile(...)`.

### 4. Discard the dry-run overlay at run end (§7.9)
After the run's videos finish, for a DRY run, best-effort remove each video's overlay directory so a
rehearsal leaves nothing behind. A clean place is the run's cleanup `finally` (where `evict_cheap`
already runs): when `wiring.dry_run`, iterate the run's video directories and
`shutil.rmtree(video_dir / ".library-overlay", ignore_errors=True)`. Import `shutil` if needed. This
must be best-effort — never let a cleanup failure fail an otherwise-finished run. (The frozen dry-run
test asserts no `.library-overlay` remains anywhere under `runs/`.)

## Constraints / do-nots
- Do NOT edit any test or change a frozen signature. Do NOT change the SDK (`sdk/`) — the `Library`
  facade and `ContextFile`/`ContextPaths` fields already exist (D-3b); this is app-side wiring only.
- The library must be namespaced by `manifest.library.namespace` (NOT mode-scoped like the cache).
- Keep `ruff`, `ruff format`, and `mypy sdk app` clean; match the surrounding supervisor style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_supervisor_library.py -q` → both pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
