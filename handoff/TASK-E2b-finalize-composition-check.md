# TASK E-2b — finalize() auto-runs the composition-DOM check (§5.8 rows 6-8, §6.5)

## Goal (one sentence)
Make `render()` persist the composition HTML so `finalize()` can recover it, and have `finalize()`
automatically run `media.graphics.check()` on every composition rendered in the run, failing the
video on any violation — in both dry and real mode.

## Governing spec (verbatim)
SDK §6.5 (`check()`):
> No AI, deterministic, and effectively free. `finalize()` runs it automatically whenever a
> composition render is among its inputs, and violations fail the video rather than warning — a chart
> drawn off-screen is not a borderline case. Call it yourself while iterating, before spending
> anything on narration.

Architecture §5.8:
> The last three run only when a composition render was among the finishing inputs …
> Failure marks the video failed rather than presenting it.

`check()` (E-2a, already merged) is real: `media.graphics.check(composition_html, *, safe_zone=True)
-> list[Violation]`, `Violation = {"kind": str, "detail": str}`. It is deterministic and free and
runs in both dry and real mode. `[output]` is not yet in the runtime Context, so use the default
`safe_zone=True` (house = tiktok); per-`[output]` safe-zone plumbing is deferred (record it, don't
build it).

## Frozen contract (already committed — do NOT edit any test)
`tests/integration/test_finalize_composition_check.py`. It renders a composition then finalizes:
a rendered composition with a violation makes `finalize()` raise `RuntimeError` whose message
contains "composition"; a clean composition finalizes to `"final.mp4"`; the check runs in dry mode
too; and a finalize with NO composition render among its inputs runs no composition check. The
existing `tests/sdk/test_finalize.py` and `tests/sdk/test_content_review.py` must stay green.

## What to implement

### 1. `render()` persists the composition HTML (`sdk/sfvf/media/graphics.py`)
`render()` computes `sha = _sha8([composition_html, duration_s])` and writes `render-{sha}.mp4` into
`ctx.paths.artifacts`. Alongside it, write the RAW composition HTML to a sidecar
`ctx.paths.artifacts / f"render-{sha}.html"` (UTF-8). This is the mechanism `finalize()` uses to
discover which compositions were rendered this run. Do not change what `render()` returns.

### 2. `finalize()` runs the composition check (`sdk/sfvf/finalize.py`)
In `_self_review` (which already runs the structural checks and, on real runs, the E-1
`content_review`), add a composition-review step that runs in BOTH modes (not gated by `dry_run` —
the composition HTML is real in a dry run, unlike the E-1 stub media). Place it so it runs
regardless of the `if dry_run: return` used by the content review — e.g. before that return, or as
its own helper called from `finalize()`.

- Discover the compositions rendered this run: glob `ctx.paths.artifacts` for `render-*.html`
  (sorted, deterministic). If none, do nothing (a non-composition finalize must be unaffected).
- For each sidecar, read its text and call `media.graphics.check(html, safe_zone=True)`.
- Collect all violations across all compositions. If any, raise
  `RuntimeError("finalize composition self-review failed: " + "; ".join(...))` where each entry is
  e.g. `f"{v['kind']}: {v['detail']}"`. The message MUST contain the word "composition" (the frozen
  test matches on it). If there are no violations, do nothing.
- `check()` requires an active context and reads `ctx.paths.artifacts`; `finalize()` already runs
  inside the active context, so call it directly (do not spawn a new context).

Do NOT change the structural checks, the house-format step, the E-1 `content_review` behavior, or
the `finalize` signature.

## Constraints / do-nots
- Do NOT edit any test or change a frozen signature; keep `tests/sdk/test_finalize.py` and
  `tests/sdk/test_content_review.py` green.
- Do NOT add `[output]` plumbing; default `safe_zone=True`.
- Do NOT try to trace which render fed the final video — checking every composition rendered this run
  is the intended v1 behavior. (A cached render whose sidecar was not re-written this run, and a
  discarded candidate render, are known v1 edges — do not build provenance tracking; they are noted
  for the hardening backlog.)
- No new dependencies. Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the SDK style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/integration/test_finalize_composition_check.py -q` → all pass.
- `-m pytest tests/sdk/test_finalize.py tests/sdk/test_content_review.py tests/sdk/test_graphics.py -q` → green.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
