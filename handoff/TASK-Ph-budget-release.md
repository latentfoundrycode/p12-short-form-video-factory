# TASK-Ph — release the budget reserve when a paid call fails (narrow-scope)

Two frozen RED contracts fail: `tests/integration/test_budget_release.py`.
1. A provider call that raises after the SDK reserved an estimate never releases the reserve; the lingering "reserved" entry keeps counting toward per_day.
2. **But** the reserved region must cover ONLY the paid call: if it also wrapped the artifact write, a call that succeeds (provider billed) then fails on the local write would release a REAL charge to 0, evading the per-day ceiling. The cost must be reconciled the instant the adapter returns, before any filesystem write.

Fix both by adding a context manager AND narrowing each site so only the paid call is inside it.

## The fix — three files

### 1. `sdk/sfvf/context.py`
Add `from contextlib import contextmanager` (and `Iterator` to the `collections.abc` import), then add this method to `Context`:

```python
@contextmanager
def _budget_reserved(self, meter: str, unit: str, estimate: float | None = None) -> Iterator[str]:
    """Reserve for a paid call and RELEASE the reserve if the block raises (so a call that fails
    at the provider does not leak its reserve toward per_day). On SUCCESS the caller reconciles
    the real cost via record_cost AFTER the block, before writing artifacts."""
    token = self._budget_reserve(meter, unit, estimate=estimate)
    try:
        yield token
    except BaseException:
        self._budget_reconcile(token, actual=0.0, note="released")
        raise
```

Do not change `_budget_reserve` or `_budget_reconcile`.

### 2. `sdk/sfvf/media/image.py`
In `generate`: put ONLY the adapter call inside the `with`; do `record_cost` and the artifact write AFTER the block (token and `out` stay in scope):

```python
    price = adapter.image_price(mdl, size)
    with ctx._budget_reserved(provider.meter, provider.unit, estimate=price) as token:
        out = adapter.generate(prompt, model=mdl, provider=provider, size=size, secrets=secrets)
    # paid call returned (provider billed) -> reconcile the KNOWN cost before any filesystem write:
    ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    dest, rel = _artifact(ctx, f"image-{stem}.{_EXT.get(out.media_type, 'png')}")
    dest.write_bytes(out.data)
    return rel
```

In `edit`: identically — only `adapter.edit(...)` inside the `with`; then `record_cost`, then `_artifact` + `write_bytes`, then `return rel`.

### 3. `sdk/sfvf/media/video.py`
In `generate`: only `adapter.generate_video(...)` inside the `with`; then reconcile with the returned cost, then write:

```python
    estimate = adapter.video_estimate(mdl, duration_s, extra)
    with ctx._budget_reserved(provider.meter, provider.unit, estimate=estimate) as token:
        out, cost = adapter.generate_video(
            prompt, model=mdl, provider=provider, first_frame_url=first_url,
            last_frame_url=last_url, ref_urls=ref_urls, duration_s=duration_s,
            extra=extra, secrets=secrets, ctx=ctx,
        )
    ctx.record_cost(provider.meter, provider.unit, cost.amount, cost.source, token=token)
    dest.write_bytes(out.data)
    return rel
```

Rationale: on an adapter failure, `record_cost` is never reached, the exception leaves the `with`, and the reserve is released (actual 0). On success, the `with` exits normally (no release), `record_cost` reconciles the real cost once, and only THEN does the fallible artifact write run — so a post-billing write failure cannot zero out a real charge.

## Scope (ONLY these three files)
- `sdk/sfvf/context.py`
- `sdk/sfvf/media/image.py`
- `sdk/sfvf/media/video.py`
Do NOT touch any test, any other file, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency (contextlib is stdlib). Minimal change.
- `ruff check`, `ruff format --check`, and `mypy` clean on all three files.

## Acceptance criteria
1. `python -m pytest tests/integration/test_budget_release.py` — BOTH tests pass (failed call releases; post-call IO failure records the real cost).
2. `python -m pytest tests/integration/test_budget_gate.py tests/integration/test_image_openai.py tests/integration/test_video_byteplus.py tests/integration/test_image_bfl.py tests/integration/test_google_image.py` — still pass (success path reconciles exactly once; no regression).
3. `ruff check` + `ruff format --check` + `mypy` clean on all three changed files.
4. git diff shows exactly those three files changed.
