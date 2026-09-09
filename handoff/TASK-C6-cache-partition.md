# TASK C-6 — cache paid/cheap partitions + LRU eviction (Architecture §5.9)

## Goal (one sentence)
Split the step cache into a `paid` partition (never auto-evicted) and a `cheap` partition (LRU-evicted
past a size ceiling), route each step by a `paid` flag, and evict the cheap partition after each run.

## Frozen contract (already committed — do NOT edit any test)
- `tests/sdk/test_cache_partition.py` — partition independence, default=cheap, `last_used` set on put
  and refreshed on get.
- `tests/sdk/test_cache_evict.py` — LRU eviction order, get-refresh affecting order, paid never
  evicted, blob GC (unreferenced deleted, shared blob kept).
- `tests/sdk/test_step_paid.py` — `ctx.step(paid=True|False)` routes to the right partition.
- `tests/core/test_cache_config.py` — `cache_max_bytes()` env parsing.
- `tests/core/test_supervisor_cache_evict.py` — a run evicts its cheap partition past the ceiling.
The existing `tests/sdk/test_cache.py` and `tests/sdk/test_step.py` must STAY green. Frozen signatures:
`StepCache(root, *, partition="cheap", now=...)`, `evict_cheap(root, *, max_bytes)`,
`ctx.step(..., paid=False)`, `cache_max_bytes()`.

## What to implement

### 1. `sdk/sfvf/cache.py` — partitioned StepCache + recency + `evict_cheap`
- **Partition layout**: entries and blobs live under the partition subtree —
  `self._entries = root / partition / "entries"`, `self._blobs = root / partition / "blobs"`. Keep
  everything else (atomic writes, `_reject_escaping_name`, restore containment checks) exactly as is.
  `partition` defaults to `CHEAP`. The two partitions are fully independent stores.
- **`last_used`**: `put` writes `{"value", "files", "last_used": self._now()}`. `get`, on a hit and
  after any successful file restore, refreshes recency by rewriting the entry with
  `last_used = self._now()` (reuse `_write_json_atomic`; preserve `value` and `files`). Do NOT refresh
  on a miss, and do NOT let the refresh change the returned value. (The existing `test_cache.py`
  round-trips must still pass — `get` still returns `raw["value"]`.)
- **`evict_cheap(root, *, max_bytes) -> int`**: operate only on `root / "cheap"`.
  - If `root/cheap/entries` does not exist, return 0.
  - Read every entry file (tolerate a malformed/unreadable one by skipping it): record its path, byte
    size, `last_used` (missing/non-numeric → treat as 0.0, i.e. evict-first), and its `files` map
    (relative → blob digest).
  - Compute total = sum(entry file sizes) + sum(sizes of every blob file present in `root/cheap/blobs`).
  - If total ≤ `max_bytes`, return 0 (touch nothing).
  - Otherwise sort entries by `last_used` ascending (oldest first; tie-break by key/path for
    determinism) and evict oldest-first: for each candidate, treat it as removed, recompute the set of
    blob digests still referenced by the *surviving* entries, and recompute
    total = sum(surviving entry sizes) + sum(sizes of referenced-and-present blobs). Stop as soon as
    total ≤ `max_bytes` or no entries remain.
  - Then actually delete: the evicted entry files, and every blob in `root/cheap/blobs` NOT in the
    final surviving-referenced digest set. Never touch `root/paid`. Return the number of entries
    evicted. Deletion must be resilient (a blob already gone is fine).

### 2. `sdk/sfvf/context.py` — route `_Step` by `paid`
`_Step.__enter__`/`__exit__` already choose the cache; make both use
`StepCache(cache_root, partition=(PAID if self._paid else CHEAP))` for the get and the put (import
`CHEAP, PAID` from `sfvf.cache`). Nothing else about the step boundary changes.

### 3. `app/core/cache_config.py` — implement `cache_max_bytes`
Read `SFVF_CACHE_MAX_BYTES`. Unset → `DEFAULT_CACHE_MAX_BYTES`. Present → parse as `int`; a
non-integer or negative value → `DEFAULT_CACHE_MAX_BYTES`; `0` is valid (returns 0). Re-add
`import os`.

### 4. `app/core/supervisor.py` — evict after a run
After a run reaches a terminal state, evict the run's cheap cache best-effort:
`from sfvf.cache import evict_cheap` and `from app.core.cache_config import cache_max_bytes`. Once
`cache_root` is known and the run's work is done (place it so it runs for a completed/partial/failed/
stopped run — e.g. just before returning the finished request, or in the cleanup `finally` guarded by
`cache_root` being defined), call `evict_cheap(cache_root, max_bytes=cache_max_bytes())` inside a
`try/except Exception` that logs and swallows — a housekeeping failure must never fail an otherwise
finished run. Do not evict before the run's steps have finished.

## Constraints / do-nots
- Do NOT edit any test; keep `tests/sdk/test_cache.py` / `test_step.py` green.
- Do NOT change the step key derivation, the canonicalisation, or the restore path-safety checks.
- Do NOT add a dependency. Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the module style.
- Eviction is per cache root (workflow + mode); a single global ceiling is out of scope for C-6.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_cache_partition.py tests/sdk/test_cache_evict.py tests/sdk/test_step_paid.py tests/sdk/test_cache.py tests/sdk/test_step.py tests/core/test_cache_config.py tests/core/test_supervisor_cache_evict.py -q` → all pass.
- `-m pytest -q` (full suite) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
