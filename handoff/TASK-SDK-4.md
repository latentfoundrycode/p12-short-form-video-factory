# TASK SDK-4 — Context identity/reporting + dry-run (supervisor wiring)

**Builder:** Cursor. **You implement product code only.** Do NOT modify any test or stub
(`tests/**`), this brief, or anything under `handoff/`. The contract test
`tests/core/test_context_wiring.py` and the stub `tests/stubs/caching/` are frozen — make them
pass by changing product code.

This is the final increment of the SDK/step-mechanism stage. It wires the runtime identity and the
content-addressed cache root into `context.json` (Workflow SDK §3.2, §4.1–§4.3, §5.9) and exposes the
§4.1 accessors, `ctx.dry_run`, and `ctx.decision()` on `Context`. SDK-1/2/3 already shipped
`step_key`/`StepCache`, `ctx.step`, and `ctx.map`; this closes the loop by having the supervisor
populate the two fields those added but never filled (`ContextPaths.cache`, `ContextFile.workflow_version`)
plus the new identity fields, so a real run can actually cache.

## What the workflow must be able to read (Workflow SDK §4.1–§4.2)

The stub reads all of these; the contract asserts their values:

```
ctx.workflow_id        # str  — the workflow's id
ctx.workflow_version   # str  — already present; must now be populated by the supervisor
ctx.run_id             # str  — the run folder name, e.g. "20260901-143022"
ctx.video_index        # int  — 1-based index of THIS video (0 for the prepare context)
ctx.video_count        # int  — how many videos this request produces
ctx.dry_run            # bool — user's dry-run flag
ctx.step_concurrency   # int  — user's parallel-steps setting (defaults to 1)
ctx.video_dir          # Path — == ctx.paths.video
ctx.shared_dir         # Path — == ctx.paths.shared
ctx.workflow_dir       # Path — the workflow's own folder (read-only)
```

`ctx.artifacts`, `ctx.settings`, `ctx.paths`, `ctx.instructions`, `ctx.previous`, `ctx.shared`
already exist — leave them.

## 1. `sdk/sfvf/emit.py` — add a `decision` emitter

Mirror the existing `log`/`stage`/`heartbeat` helpers. Emit event **type `"decision"`** with these
exact keys (omit `alternatives`/`reason` only when `None`):

```python
def decision(
    kind: str,
    chosen: str,
    *,
    alternatives: list[str] | None = None,
    reason: str | None = None,
) -> None:
    event: dict[str, Any] = {"t": "decision", "kind": kind, "chosen": chosen}
    if alternatives is not None:
        event["alternatives"] = alternatives
    if reason is not None:
        event["reason"] = reason
    emit(event)
```

## 2. `sdk/sfvf/context.py`

**`ContextPaths`** — add one optional field (defaulted so existing `context.json` still validates):

```python
workflow: Path | None = Field(
    default=None,
    description="The workflow's own folder (read-only).",
)
```

Keep the existing `cache: Path | None = None` field.

**`ContextFile`** — add these fields, **all defaulted** (existing `context.json` files, and every
current supervisor test that builds a `ContextFile` without them, must keep validating):

```python
workflow_id: str = Field(default="", description="The workflow's id.")
run_id: str = Field(default="", description="The run folder name.")
video_index: int = Field(default=0, description="1-based index of this video; 0 for prepare.")
video_count: int = Field(default=0, description="How many videos this request produces.")
dry_run: bool = Field(default=False, description="True when running with fake assets.")
step_concurrency: int = Field(default=1, description="User's parallel-steps setting for ctx.map.")
```

Keep the existing `workflow_version` field.

**`Context.__init__`** — expose the accessors listed above. Add:

```python
self.workflow_id = file.workflow_id
self.run_id = file.run_id
self.video_index = file.video_index
self.video_count = file.video_count
self.dry_run = file.dry_run
self.step_concurrency = file.step_concurrency
self.video_dir = file.paths.video
self.shared_dir = file.paths.shared
self.workflow_dir = file.paths.workflow
```

**`Context.decision`** — a thin method over the emitter (import `decision` from `.emit`):

```python
def decision(
    self,
    *,
    kind: str,
    chosen: str,
    alternatives: list[str] | None = None,
    reason: str | None = None,
) -> None:
    decision(kind, chosen, alternatives=alternatives, reason=reason)
```

(The stub calls `ctx.decision(kind="model", chosen="alpha", alternatives=["beta"], reason="unit test")`.)

## 3. `app/paths.py` — add the cache root constant

```python
CACHE_DIR = APP_ROOT / "cache"
```

## 4. `app/core/supervisor.py` — populate `context.json`

The cache must persist **across runs** (SDK §5.9: "a later run on a different day costs nothing"),
so it lives outside any single run folder, partitioned per workflow **and by run mode**:

```
mode = "dry" if dry_run else "real"
cache_root = ((cache_dir or CACHE_DIR) / workflow_id / mode).resolve()
```

**Why the mode segment is mandatory (do not drop it):** `step_key` does not include `dry_run`, so
without a mode-partitioned root a dry run (fake assets, SDK §4.2) and a real run of the same step with
the same inputs would share one cache entry. A dry run would then poison the paid cache — a later real
run would be served the placeholder asset and skip real generation. The `real` and `dry` subtrees keep
the two fully isolated; a dry run may reuse earlier *dry* results, never real ones, and vice-versa. The
contract test's third run exercises exactly this: after two dry runs it launches a real run with the
same inputs and asserts every step re-executes (`status=="ok"`, body runs) rather than hitting the dry
cache.

`run_request` — add three keyword params (defaulted; the API layer does not pass them yet):

```python
cache_dir: Path | None = None,
dry_run: bool = False,
step_concurrency: int = 1,
```

Compute `cache_root` once `workflow_id` is known, and `cache_root.mkdir(parents=True, exist_ok=True)`.
Thread the identity + cache values through to **both** context-building sites:

- **`_run_prepare`** (the shared/prepare context): set `workflow_version`, `workflow_id`, `run_id`,
  `video_count`, `dry_run`, `step_concurrency`, `paths.cache=cache_root`, `paths.workflow=workflow_dir`,
  and `video_index=0` (prepare is not a specific video).
- **`_run_one_video`** (the per-video context): same, but `video_index=index` (the 1-based video number).

`workflow_version` comes from the parsed manifest (`workflow.version`); `workflow_dir` is the already
`.resolve()`d directory `run_request` holds; `run_id` is the allocated run folder name.

**Recommended structure (your call):** the two context builders already take many kwargs. Consider a
small frozen dataclass carrying the run-wide wiring (`workflow_id`, `run_id`, `workflow_version`,
`video_count`, `cache_root`, `workflow_dir`, `dry_run`, `step_concurrency`) and pass that one object to
both `_run_prepare` and `_run_videos`/`_run_one_video`, rather than eight loose parameters. Only the
observable result in `context.json` is contract; the plumbing shape is yours.

## Acceptance (the frozen contract test)

`tests/core/test_context_wiring.py` drives the real supervisor against `tests/stubs/caching` and asserts:

1. **Identity in the event stream** — the stub emits an `identity` event per video carrying every
   accessor; the test checks `workflow_id=="caching"`, `workflow_version=="1.0.0"`, `run_id`==run folder,
   `video_index`==1/2, `video_count==2`, `dry_run is True`, `step_concurrency==3`, and that `video_dir`,
   `shared_dir`, `workflow_dir` are the resolved paths.
2. **`decision` event** — `{"t":"decision","kind":"model","chosen":"alpha","alternatives":["beta"],"reason":"unit test"}`.
3. **`context.json` on disk** — carries `workflow_version`, `workflow_id`, `run_id`, `video_index`,
   `video_count`, `dry_run`, `step_concurrency`, `paths.workflow == <stub dir>`, and the
   mode-partitioned `paths.cache`: `<cache_dir>/caching/dry` for the dry runs,
   `<cache_dir>/caching/real` for the real run.
4. **Cross-run caching** — three runs share one `cache_dir`. Run 1 (dry, cold): each video's `step`
   event has `status=="ok"` and the body log `"computing-body"` appears. Run 2 (dry, warm): each `step`
   event has `status=="cached"` and the body log is **absent** (restored from the dry cache). Run 3
   (real, `dry_run=False`, same inputs): each `step` event has `status=="ok"` and the body runs again —
   the real partition never sees the dry entries (no cache poisoning).

## Full local gate (all six must pass — run from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Do not weaken, skip, or edit any test to make the gate pass. Existing supervisor tests that build a
`ContextFile` or call `run_request` without the new fields must still pass — that is why every new field
is defaulted.
