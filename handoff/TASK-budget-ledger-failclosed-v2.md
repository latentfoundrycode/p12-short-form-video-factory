# TASK — budget ledger fail-closed, COMPLETION (H23 remaining paths + H59)

## Why (round 2)
Cross-family review rejected the first H23 fix as incomplete: not ALL ledger filesystem/integrity
faults become `BudgetError`, so `check_atomic_budget` (which catches only `BudgetError`) still strands
atomic runs `running` on those faults. Three paths remain (frozen RED at HEAD):
1. `_read_ledger` calls `path.is_file()` OUTSIDE its try, so a stat `PermissionError`/`OSError` escapes raw.
2. The interprocess **lock acquisition** in `_held()` (`_interprocess_lock`: mkdir + open + `_lock_exclusive`)
   can raise `OSError` (a fault, or a Windows `msvcrt.locking` timeout), which escapes raw.
3. **H59:** `_token_states` silently `continue`s past a `reserved`/`actual` line missing its token, which
   under-counts spend (the engine always writes a token, so a token-less spend line is corruption).

Keep the round-1 changes (`_read_ledger` read_text `OSError`→BudgetError; `_snapshot` wraps
`ValueError`/`OverflowError`; `check_atomic_budget` catches `BudgetError`) — this ADDS the missing paths.

Frozen RED tests (committed): `test_a_stat_oserror_fails_closed`, `test_a_lock_acquisition_oserror_fails_closed`,
`test_a_spend_record_missing_its_token_fails_closed` in `tests/sdk/test_budget.py`.

## Changes — all in `sdk/sfvf/_budget.py`

### 1. `_read_ledger` — is_file inside the try
Move the `if not path.is_file(): return []` INSIDE the existing `try` so a stat fault converts:
```python
def _read_ledger(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise BudgetError("budget ledger is unreadable") from exc
    ...
```

### 2. `_interprocess_lock` — acquisition OSError → BudgetError (close the handle on failure)
```python
@contextmanager
def _interprocess_lock(lock_path: Path) -> Iterator[None]:
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
    except OSError as exc:
        raise BudgetError("budget ledger lock is unavailable") from exc
    with handle:
        try:
            _lock_exclusive(handle)
        except OSError as exc:
            raise BudgetError("budget ledger lock is unavailable") from exc
        try:
            yield
        finally:
            _unlock_exclusive(handle)
```
(`with handle:` guarantees the file handle is closed even when `_lock_exclusive` raises. The `yield`/
`_unlock_exclusive` body is unchanged; a body exception still propagates as-is.)

### 3. `_token_states` — a token-less spend record fails closed (H59)
```python
    for entry in entries:
        token = entry.get("token")
        kind = entry.get("kind")
        if not isinstance(token, str) or not token:
            if kind in ("reserved", "actual"):
                raise BudgetError("budget ledger spend entry is missing its token")
            continue
        state = states.setdefault(token, _TokenState())
        # ... existing reserved/actual handling, unchanged ...
```
(A non-spend line without a token is still skipped; only a `reserved`/`actual` line without a token —
real corruption — fails closed. `_snapshot`'s `except (ValueError, OverflowError)` does NOT catch this
`BudgetError`, so it propagates correctly; `read_run_spend` already catches `BudgetError` and stays
best-effort.)

### 4. `_append_line` — write faults fail closed (uniformity)
Wrap the file operations so a write `OSError` (disk full, permission) during `reserve`/`reconcile`
becomes `BudgetError` (fail closed — a reservation that could not be recorded must not proceed):
```python
def _append_line(path: Path, record: dict[str, str | float]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(record, allow_nan=False) + "\n").encode("utf-8")
        if not path.is_file():
            path.touch()
        with path.open("r+b") as handle:
            ...  # existing seek/truncate/write/flush/fsync body, unchanged
    except OSError as exc:
        raise BudgetError("budget ledger is unwritable") from exc
```
(`json.dumps` stays inside; only the filesystem ops need the guard, but wrapping the whole body is fine
since `json.dumps(allow_nan=False)` raises `ValueError` for a bad number — which must NOT be swallowed
here, so keep `json.dumps` OUTSIDE the try, or catch only `OSError`. Catch ONLY `OSError`, as shown.)

## Scope
Only `sdk/sfvf/_budget.py`. Do NOT change `_require_amount`, `check_atomic_budget` (already correct),
`read_run_spend`, or the frozen tests. No new dependencies. Also move H59 into `docs/HARDENING.md` (a new
Resolved entry noting this PR) alongside the already-Resolved H23/H28.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_budget.py tests/core/test_preflight.py tests/integration/test_budget_gate.py tests/sdk/test_budget_report.py -q` → all pass (the 3 new completeness tests plus every prior budget/preflight test — corrupt-line, torn-tail, bad-amount, bad-estimate/actual argument tests must stay green; the concurrency/lock tests must still work since a HEALTHY lock path is unchanged).
- `ruff check sdk app tests` and `ruff format --check sdk app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
