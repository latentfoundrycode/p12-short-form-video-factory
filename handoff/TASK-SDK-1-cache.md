# TASK-SDK-1 — Content-addressed step cache (SDK side)

## One-line task and why
Implement the content-addressed step cache the step mechanism will build on: a stable key from the
workflow version + step family + inputs (canonical order, files hashed by content, label absent) and
a filesystem store that round-trips a step's JSON result and its files. Architecture §5.9; Workflow
SDK §5.2a (how caching decides it has seen this before), §5.3 (a step is a pure function of its
declared inputs), §5.5 (returning files). First increment of the SDK/step-mechanism stage.

This lives in the **SDK** (`sdk/sfvf/`), which runs inside the isolated workflow venv and must not
import `app`. It is pure Python (hashlib/json/pathlib/shutil) — no subprocess, no new dependency.

## The failing reviewer test to make pass (already written — DO NOT modify it)
`tests/sdk/test_cache.py` imports `from sfvf.cache import StepCache, step_key` and fails on `main`
with `ModuleNotFoundError`. It is the contract. Make it pass by implementing the module; do not edit,
weaken, or delete the test or any assertion.

## API to implement in `sdk/sfvf/cache.py`

```python
def step_key(workflow_version: str, family: str, inputs: dict[str, Any]) -> str: ...

class StepCache:
    def __init__(self, root: Path) -> None: ...
    def get(self, key: str, *, restore_into: Path | None = None) -> Any | None: ...
    def put(self, key: str, value: Any, *, files: Mapping[str, Path] | None = None) -> None: ...
```

### `step_key(workflow_version, family, inputs) -> str`
- Returns a **64-char lowercase SHA-256 hex** digest of, together: the workflow version, the family,
  and the `inputs` in a **canonical form** — serialize with sorted keys so input key ORDER never
  changes the key (§5.9 "canonical form matters").
- **Any `pathlib.Path` value anywhere in `inputs` (including nested in lists/dicts) is replaced, for
  keying purposes, by the SHA-256 of that file's CONTENT — never its path string** (§5.9/§5.3). So the
  same file at two different paths keys identically; a different file at the same path keys
  differently. (Read the file's bytes to hash; assume Path inputs point at existing files.)
- `label` is deliberately NOT a parameter — it must never influence the key.
- Changing the version, the family, or any input value must change the key.

### `StepCache` — a content-addressed store rooted at `root`
- **`put(key, value, files=None)`**: store `value` (JSON-serializable) under `key`. `files` maps a
  relative name (e.g. `"final.mp4"`, `"sheets/bertie.png"`) to the source file to store. Store each
  file's bytes **by content hash** (so identical content dedupes naturally) and record the
  relative-name → content-hash mapping alongside the value. Writes must be **atomic** (write to a temp
  name in the same dir, then `os.replace`) — mirror the pattern in `sdk/sfvf/runner.py`'s
  `_write_result` / `app/core/records.py`'s `write_json_atomic`. Create `root` as needed.
- **`get(key, restore_into=None) -> Any | None`**: return the stored `value`, or `None` if `key` is
  absent. If `restore_into` is given and the entry has stored files, write each back to
  `restore_into / <relative-name>` (creating nested parent dirs), byte-for-byte.
- The store is on disk, so a **fresh `StepCache(same_root)` sees what a previous instance stored**
  (the test asserts this — no in-memory-only state).

Keep it simple and correct: a single content-addressed store. Do NOT implement the paid/cheap
partition or LRU eviction (those need cost info from the budget engine — a later stage). Do NOT walk
`value` to auto-detect file paths; files are passed explicitly via `files`.

## Scope — files you may change
- `sdk/sfvf/cache.py` (new)

## Do NOT touch
- `tests/**` (make the reviewer test pass by implementing the module), `app/`, other `sdk/` files,
  `frontend/`, `.github/`, `docs/`, `handoff/`. Do not add dependencies. Do not weaken any test or CI.

## Acceptance
- `tests/sdk/test_cache.py` passes.
- The full six-command gate is green (pytest count is 151 existing + 6 new cache tests = 157).

## Gate — run all six before committing (worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
Note: `sdk/sfvf/cache.py` is under mypy's strict scope (`files = app, sdk, tools`) — it must type-check
strictly (annotate fully; no `Any` leaks beyond the `value`/`inputs` boundaries the signatures allow).

## Commit message (house style — imperative subject stating change and rationale)
```
Add a content-addressed step cache keyed on workflow version, family, and content-hashed inputs so step results reuse correctly across runs and never collide on a reused path.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files you changed, the commit hash, and the final pytest count.
