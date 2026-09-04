# TASK B-4b — per-provider rate-limiter scaffolding (§5.5)

**Builder:** Cursor. **Product code only.** Create `sdk/sfvf/_ratelimit.py` (new, internal/underscore module).
Do NOT modify, add, or delete anything under `tests/`, `docs/`, or `handoff/`. The reviewer contract
`tests/sdk/test_ratelimit.py` is FROZEN — make it pass by writing product code.

This is the central rate limiter the provider adapters (OpenRouter next, Higgsfield later) route every request
through: **one queue per provider**, so a provider's own caps are respected no matter how many steps run at
once (§5.5). It is *scaffolding* — minimal but real and extensible; do not over-build.

## Implement `sdk/sfvf/_ratelimit.py`

A `RateLimiter` class plus a module-level shared instance the adapters will import.

```python
class RateLimiter:
    def __init__(self, *, monotonic=time.monotonic, sleep=time.sleep) -> None: ...
    def configure(self, provider: str, *, max_concurrency: int = 1, min_interval_s: float = 0.0) -> None: ...
    @contextmanager
    def slot(self, provider: str) -> Iterator[None]: ...
    def penalize(self, provider: str, retry_after_s: float) -> None: ...
```

Required behaviour (the frozen tests pin all of it):

- **Injectable clock:** `__init__` takes `monotonic` and `sleep` callables (defaulting to `time.monotonic` /
  `time.sleep`) and uses ONLY those for timing — so tests can drive it deterministically with a fake clock.
- **Per-provider state, lazily created.** An unconfigured provider behaves as `max_concurrency=1`,
  `min_interval_s=0.0`. `configure(provider, ...)` sets its caps. State is keyed by provider name; different
  providers share nothing (independent queues, semaphores, and back-off deadlines).
- **`slot(provider)` context manager:**
  1. Acquire the provider's concurrency permit — a `threading.Semaphore(max_concurrency)`. This blocks while
     `max_concurrency` slots are already held, and is released on context exit (use try/finally).
  2. Then, under a per-provider lock, compute the wait:
     `wait = max(0.0, not_before - now, last_start + min_interval_s - now)`
     where `now = self._monotonic()`, `not_before` is the current back-off deadline (0 initially), and
     `last_start` starts as negative-infinity (so the first call never waits for pacing).
     **Call `self._sleep(wait)` only when `wait > 0`** (don't record spurious zero sleeps).
  3. Set `last_start = self._monotonic()` (after any wait), then `yield`.
- **`penalize(provider, retry_after_s)`:** set the provider's back-off deadline to
  `not_before = max(not_before, self._monotonic() + retry_after_s)` — i.e. take the **max**, never the sum, so
  repeated/overlapping `Retry-After` hints don't stack, and a shorter one can't shorten an existing back-off.
  The adapter calls this when a provider returns `429` with a `Retry-After`.
- **Thread-safety:** guard the per-provider mutable state (`not_before`, `last_start`, and the state registry)
  with locks; concurrency is enforced by the per-provider semaphore. `configure` on an existing provider
  updates its caps (rebuild/replace the semaphore to the new `max_concurrency`).
- **Shared instance:** also expose a module-level `LIMITER = RateLimiter()` (default clock) that the OpenRouter
  adapter (B-4c) will import and `configure("openrouter", ...)` on. That's all — no adapter code here.

mypy-strict clean, no new dependencies (stdlib `threading`, `time`, `contextlib`, `math`, `typing` only).
Touch only the new `sdk/sfvf/_ratelimit.py`.

## Acceptance

- `tests/sdk/test_ratelimit.py` passes (5 tests): min-interval pacing, `Retry-After` back-off, back-off takes
  the max not the sum, provider independence, concurrency cap blocks until release.
- Nothing else in the suite regresses.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/sdk/test_ratelimit.py
```
(The full `pytest` run also shows 3 pre-existing failures in `finalize`/`example_workflow` — those are ONLY the
HyperFrames toolchain not being installed in this worktree; CI installs it and runs them green. Ignore them.)
