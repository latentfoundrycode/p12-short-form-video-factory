# TASK-Ph — release the budget reserve when a paid call fails

A frozen RED contract fails: `tests/integration/test_budget_release.py`. A provider call that raises
after the SDK reserved a budget estimate never releases the reserve; the lingering "reserved" ledger
entry keeps counting toward the per-day ceiling (a token's effective spend falls back to its reserved
amount). Fix by releasing the reserve on failure, via a small context manager used at the three
reserve→call→reconcile sites.

## The fix — three files

### 1. `sdk/sfvf/context.py`
Add a context manager method to `Context` (add `from contextlib import contextmanager` to the imports):

```python
@contextmanager
def _budget_reserved(self, meter: str, unit: str, estimate: float | None = None):
    """Reserve for a paid call and RELEASE the reserve if the block raises (so a failed call
    does not leak its reserve toward per_day). On success the caller reconciles via record_cost."""
    token = self._budget_reserve(meter, unit, estimate=estimate)
    try:
        yield token
    except BaseException:
        self._budget_reconcile(token, actual=0.0, note="released")
        raise
```

(`_budget_reserve` returns a valid token or raises; `_budget_reconcile` with `actual=0.0` writes an
"actual" 0 entry, note "released", which supersedes the reserve so it no longer counts. Both already
exist — do not change them.)

### 2. `sdk/sfvf/media/image.py`
In BOTH `generate` and `edit`, replace the bare reserve line

```python
    token = ctx._budget_reserve(provider.meter, provider.unit, estimate=price)
    out = adapter.generate(...)          # (or adapter.edit(...) in edit)
    dest, rel = _artifact(...)
    dest.write_bytes(out.data)
    ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    return rel
```

with the block wrapped in the context manager, keeping the SAME body (adapter call, artifact write,
and `record_cost`) INSIDE the `with` so a successful call still reconciles exactly once:

```python
    with ctx._budget_reserved(provider.meter, provider.unit, estimate=price) as token:
        out = adapter.generate(...)      # (or adapter.edit(...))
        dest, rel = _artifact(...)
        dest.write_bytes(out.data)
        ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    return rel
```

### 3. `sdk/sfvf/media/video.py`
In `generate`, do the same: wrap the reserve→`adapter.generate_video(...)`→`dest.write_bytes`→
`ctx.record_cost(...)` body in `with ctx._budget_reserved(provider.meter, provider.unit, estimate=estimate) as token:`, keeping `record_cost` inside the `with`.

Do NOT reconcile twice: `record_cost` stays the only success-path reconcile, inside the block; the
context manager releases ONLY when the block raises.

## Scope (ONLY these three files)
- `sdk/sfvf/context.py`
- `sdk/sfvf/media/image.py`
- `sdk/sfvf/media/video.py`
Do NOT touch any test, any other file, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency (contextlib is stdlib). Minimal change.
- `ruff check`, `ruff format --check`, and `mypy` clean on all three files.

## Acceptance criteria
1. `python -m pytest tests/integration/test_budget_release.py` — passes (failed call releases its reserve).
2. `python -m pytest tests/integration/test_budget_gate.py tests/integration/test_image_openai.py tests/integration/test_video_byteplus.py tests/integration/test_image_bfl.py` — still pass (the success path reconciles exactly once; no regression).
3. `ruff check` + `ruff format --check` + `mypy` clean on all three changed files.
4. git diff shows exactly those three files changed.
