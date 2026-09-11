# TASK E-2b cache fix — composition sidecar must survive a step-cache hit

## Problem (review BLOCKING finding)
`render()` writes a `render-{sha}.html` composition sidecar next to its `render-{sha}.mp4`, and
`finalize._composition_review()` recovers compositions by globbing `render-*.html`. But the step
cache only persists files NAMED in the step's return value (`_video_files(value)` in
`sdk/sfvf/context.py`), which is just the `.mp4`. So on a cache HIT the `.mp4` is restored but the
`.html` sidecar is not — `_composition_review` finds no sidecar and silently skips the §6.5 check.
Because the render step caches on `with`-exit BEFORE finalize runs, a composition that would fail
the check still gets its `.mp4` cached, and a later run with the identical composition restores the
`.mp4` (sidecar absent) and passes finalize unchecked. The gate must not be bypassable by caching.

## Fix (apply EXACTLY; one file: `sdk/sfvf/context.py`)
Make a render's composition sidecar travel with its cached video: when the step caches its files,
include, for every captured `.mp4`, a same-stem `.html` sidecar if one exists on disk.

1. Add this module-level helper right AFTER the existing `_video_files` function:

```python
def _add_composition_sidecars(files: dict[str, Path], video: Path) -> None:
    """Include a render's composition-HTML sidecar (``render-<sha>.html``) with its cached ``.mp4``.

    ``media.graphics.render`` writes the composition sidecar next to its ``.mp4`` but it is not named
    in the step's return value, so it is not captured by ``_video_files``. Without this, a cache hit
    restores only the ``.mp4`` and ``finalize``'s §6.5 composition check is silently bypassed. For
    each captured ``.mp4``, add its same-stem ``.html`` sidecar when present so both are cached and
    restored together.
    """
    for relative in list(files):
        if relative.endswith(".mp4"):
            sidecar = f"{relative[:-4]}.html"
            candidate = video / sidecar
            if candidate.is_file():
                files[sidecar] = candidate
```

2. In `_Step.__exit__`, call it right after `files = _video_files(...)` and before `put(...)`:

```python
        files = _video_files(self.value, self._ctx.paths.video)
        _add_composition_sidecars(files, self._ctx.paths.video)
        self._step_cache().put(self._key, self.value, files=files)
```

Change nothing else.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_step.py -q` → all pass, including
  `test_step_caches_and_restores_composition_sidecar` (the locking test — do NOT edit it).
- `-m pytest tests/sdk/test_step.py tests/sdk/test_cache.py tests/sdk/test_cache_partition.py tests/integration/test_example_workflow.py tests/integration/test_finalize_composition_check.py -q` → green.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
