# TASK — web-image-sourcing inc6 FIX round 6: the runtime web-tier governance off-switch (DESIGN §5)

## Why this round
Cross-family review found the design-mandated **runtime governance off-switch** missing. `DESIGN §5`
(docs/DESIGN-web-image-sourcing.md, "Governance off-switch (enforced at RUNTIME, not just scan-time)")
requires **an owner setting to disable the `web` tier even when a key is present**, carried into the
run `Context` and **re-checked inside the `media.web` calls** — "the enforcement point is the SDK
call, not only manifest validation," because a workflow that calls the SDK directly would bypass a
scan-time-only flag. Today any `sources=("web",)` call loads the secret and dispatches SerpApi
whenever the key exists; the owner cannot turn the tier off.

The policy is **owner-controlled**, so it must NOT live in the workflow-controlled
`ContextFile.settings`/`params`. It mirrors `budget`: an env-gated owner setting → the app →
`_ContextWiring` → `ContextFile` → `Context` → checked in `media.web`.

Frozen RED contracts are committed (HEAD~1 = SDK enforcement in `tests/integration/test_media_web_web.py`;
HEAD = the loader in `tests/core/test_web_tiers.py`).

## Changes

### A. SDK — `sdk/sfvf/context.py`
1. Add an owner-controlled field to `ContextFile` (near `budget`/`secrets`):
```python
    disabled_web_tiers: list[str] = Field(
        default_factory=list,
        description="Owner governance off-switch (DESIGN §5): web-image tiers refused at runtime "
        "even when their key is present. Owner-controlled, distinct from workflow `settings`.",
    )
```
2. In `Context.__init__`, store it normalized and expose an accessor:
```python
        self._disabled_web_tiers = frozenset(file.disabled_web_tiers)
```
```python
    def web_tier_enabled(self, tier: str) -> bool:
        """False when the owner has disabled this web-image tier (DESIGN §5 off-switch)."""
        return tier not in self._disabled_web_tiers
```

### B. SDK — `sdk/sfvf/media/web.py`
1. Define a module-level error (so `media.web.WebTierDisabledError` is importable):
```python
class WebTierDisabledError(RuntimeError):
    """A search/source targeted a web-image tier the owner disabled at runtime (DESIGN §5)."""
```
2. In `search()`, after the existing `sources` subset validation and **before** the `ctx.dry_run`
   branch (so it fires in dry-run AND real, before any secret load or dispatch), refuse any requested
   tier the owner disabled:
```python
    disabled = [s for s in sources if not ctx.web_tier_enabled(s)]
    if disabled:
        raise WebTierDisabledError(
            f"web-image tier(s) {disabled} disabled by owner policy (DESIGN §5 off-switch)"
        )
```
   `source()` composes `search()`, so this covers `source()` too — no change needed there.

### C. App wiring — mirror `budget` exactly (env → app.state → supervisor → wiring → ContextFile)
1. **New loader** `app/core/web_tiers.py::load_disabled_web_tiers() -> list[str]` (frozen by
   `tests/core/test_web_tiers.py`): read env `SFVF_DISABLE_WEB_TIERS`; unset/empty → `[]`; otherwise
   split on commas, strip each, drop blanks, lowercase, de-duplicate preserving first-seen order.
2. **`app/main.py`** (~line 107, beside the `application.state.budget = ...` line): set
   `application.state.disabled_web_tiers = load_disabled_web_tiers()` (import the loader).
3. **`app/core/supervisor.py`**:
   - `_ContextWiring`: add `disabled_web_tiers: list[str] = field(default_factory=list)`.
   - Thread it from the supervisor entry the SAME way `budget` is threaded: the run entry that
     receives `budget` (the `budget: BudgetConfig | None = None` parameter chain fed from
     `app.state.budget`) also receives `disabled_web_tiers: list[str] | None = None` and passes it
     into the `_ContextWiring(...)` construction (line ~436) as
     `disabled_web_tiers=disabled_web_tiers or []`. Grep `app.state.budget` and the `budget=`
     parameter path to find every call site and add the parallel argument, defaulting to `[]`.
   - In `_make_context(...)` (the `ContextFile(...)` build, ~line 268), add
     `disabled_web_tiers=wiring.disabled_web_tiers`.
   Keep the change purely additive — every existing caller that omits the new argument gets `[]`
   (nothing disabled), so behaviour is unchanged unless the owner sets the env var.

## Scope
SDK: `sdk/sfvf/context.py`, `sdk/sfvf/media/web.py`. App: `app/core/web_tiers.py` (new),
`app/main.py`, `app/core/supervisor.py`. Do NOT touch the serpapi adapter, `_http.py`, `_budget.py`,
the registry/meters, other adapters, or the frozen tests. No new dependencies. Never read/log the key.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py tests/core/test_web_tiers.py -q`
  → all pass (the whole web contract, which was gated on the new field, goes green; the governance
  tests and the loader tests pass).
- `PYTHONPATH=sdk python -m pytest tests/api tests/core -q` → still pass (the supervisor/context
  wiring change is additive; confirm nothing regressed, especially context.json (de)serialization and
  any supervisor/run tests).
- `ruff check .` (or `sdk app tests`) and `ruff format --check .` clean; `python -m mypy` if it runs
  in your env.
- Confirm end-to-end by inspection: with `SFVF_DISABLE_WEB_TIERS=web`, a run's `context.json` carries
  `disabled_web_tiers: ["web"]` and `media.web.search(sources=("web",))` raises
  `WebTierDisabledError` before any dispatch.
