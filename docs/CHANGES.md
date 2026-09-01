# Changes

A running log of notable changes outside the per-task build history.

## 2026-09-01 — SDK-3: ctx.map, parallel steps of one family

Third increment of the SDK/step-mechanism stage (Workflow SDK §4.7). `sdk/sfvf/context.py` gains
`ctx.map(family, items, *, inputs, fn, label=None, concurrency=1, on_error="raise")`: each item runs
as a full `ctx.step` (inheriting caching, file handling, and the `step` event), across a
`ThreadPoolExecutor` bounded by `concurrency`, with results returned in INPUT order regardless of
completion order. `on_error="raise"` returns `list[value]` and propagates the first failure;
`on_error="collect"` returns `list[Outcome]` (`value`/`error`/`ok`). `sdk/sfvf/emit.py` now serializes
write+flush under a module lock so the concurrent `step` events cannot tear a line in `events.jsonl`.

**Supervisor technical decisions (recorded):**
- **`on_error="collect"` catches `Exception`, not `BaseException`.** The first attempt caught
  `BaseException`; the cross-family reviewer (GPT-5.6 Sol) flagged that this would swallow
  process-control signals (`SystemExit`/`KeyboardInterrupt`/`GeneratorExit`). Corrected to `except
  Exception` so those propagate; `Outcome.error` typed `Exception | None`. (The two reviewers split on
  this — Opus judged the broad catch "defensible" for worker threads, Sol rejected it; the fix is
  standard best practice and satisfies both.)
- **Cancellation-between-items DEFERRED.** §4.7's "cancellation is honoured between item completions"
  ties to the stop-sentinel mechanism, which is not wired at the SDK boundary yet. Deferred to a later
  increment; recorded so it is not mistaken for missing.

Both reviewers APPROVED the final diff; gate green (175 passed, 1 skipped).

## 2026-09-01 — SDK-2: ctx.step, the cached step boundary

Second increment of the SDK/step-mechanism stage. `sdk/sfvf/context.py` gains `ctx.step(family, *,
inputs, label=None)` — a context manager over the SDK-1 cache (Workflow SDK §4.5, §5.1-§5.5). On a
hit it returns the stored result and restores its files without running the body; on a miss it runs
the body, and `step.set(value)` stores the result plus any files the value names. It emits a `step`
event (`{t, name, key, label, status}`), the `label` is display-only (never in the key), and a body
that raises stores nothing. Two OPTIONAL context fields were added (`ContextPaths.cache`,
`ContextFile.workflow_version`, both defaulted so existing `context.json` still validates); the
supervisor does not populate them yet (SDK-2b wires that).

**Supervisor technical decisions (recorded):**
- **File paths are VIDEO-relative (SDK §5.5), not artifacts-relative.** The first attempt (and the
  original reviewer test) treated returned paths as relative to `ctx.artifacts`; the cross-family
  reviewer (GPT-5.6 Sol) caught that §5.5 makes them relative to the video folder. The spec settles
  it, so I corrected the test and implementation to derive/restore relative to `paths.video` — no
  escalation needed. (This is why files are written under `ctx.artifacts` but returned as e.g.
  `"artifacts/final.mp4"`.)
- **Known limitation (deferred, recorded):** a step whose result is literally `None` reads as a cache
  MISS, because SDK-1's `StepCache.get` uses `None` as its miss sentinel and `ctx.step` treats
  `found is not None` as the hit signal. The failure mode is a benign re-run (never a stale result),
  and no realistic step returns `None`. Closing it would be a `StepCache` API change (a distinct
  "exists" signal) — deferred; noted here so it is not rediscovered as a surprise.

Both reviewers APPROVED the final diff; gate green. (Process note: the reviewer test had two lint-only
reflows by the implementer — import grouping + a combined `with`, assertions unchanged — a consequence
of lint nits in the authored test; lesson recorded to lint contract tests before delegating.)

## 2026-09-01 — SDK-1: content-addressed step cache

First increment of the SDK/step-mechanism stage. Added `sdk/sfvf/cache.py`: `step_key(workflow_version,
family, inputs)` and a `StepCache` content-addressed store, per Architecture §5.9 and Workflow SDK
§5.2a/§5.3/§5.5. The key is a SHA-256 over the workflow version + family + inputs in a canonical form;
any `Path` in inputs (values or keys, nested) is hashed by file CONTENT, not path text; `label` is never
in the key. `StepCache` round-trips a JSON result plus files stored/restored by content, with atomic writes.

**Supervisor technical decisions (recorded):**
- **Scope.** A single content-addressed store. The paid/cheap partition and LRU eviction (§5.9) are
  deliberately DEFERRED to the budget-engine stage — they need per-step cost info that does not exist yet.
- **Canonicalization is unambiguous by construction.** Distinct input shapes get distinct markers so no
  two can collide in the key: a `Path` → `{"__sfvf_file_sha256__": <hex>}`, a `dict` →
  `{"__sfvf_dict__": [[k,v],… sorted]}`, a `list` stays a list. This closes a class of subtle
  wrong-cache-hit bugs (a string equal to a file digest; a dict vs a pair-shaped list).
- **Restore is path-confined to the project standard.** File restore refuses absolute/`..` names AND
  resolves each destination to verify it stays inside `restore_into` (`Path.is_relative_to`), so a
  pre-existing symlink cannot redirect a write outside it. This mirrors the file-server increment
  (005-3) — a consistency fix to the existing path-confinement standard, not new policy.

**Gate note.** This foundational primitive went through four cross-family review rounds: the decorrelated
verifier (GPT-5.6 Sol) surfaced progressively finer canonicalization/confinement edges that the
Anthropic reviewer approved past; each was fixed with a reviewer-authored test. The final round-3 finding
(dict vs pair-list) was esoteric on an otherwise-verified core; per the owner's guidance I judged it not a
stop and applied the terminal marker fix that closes the shape-ambiguity class by construction, rather
than accept it as a documented wart — keeping the two-reviewer gate intact (both APPROVE on the final diff).

## 2026-09-01 — CI action majors bumped to the Node-24 runtime

Bumped three GitHub Action majors in `.github/workflows/ci.yml` off the deprecated Node-20 action
runtime to their current Node-24 majors: `actions/checkout@v4→v5`, `actions/setup-node@v4→v7`, and
`actions/setup-python@v5→v6`. CI-config only — no product code, no test change; the gate steps,
`!cancelled()` guards, permissions, concurrency, and caching are unchanged, as is the frontend
`node-version: "20"` (the app runtime, separate from the action runtime) and `python-version: "3.12"`.

Run through the full gated loop: implemented by Cursor (Grok 4.6), Review A (diff-reviewer, Claude
Opus 4-8) APPROVE + Review B (GPT-5.6 Sol, read from a committed diff file per the hardened policy)
APPROVE, gate-integrity clean, auto-merged when the required `gate` check went green.

## 2026-09-01 — F2: hand out a run id only after request.json exists

Fixed a launch-window ordering race in `app/core/supervisor.py` (`run_request`): the
`on_started(run_id)` callback — how the run API learns the id it returns from `POST /runs` — fired
**before** `request.json` was written, so a client reading the run immediately after the 202 could
race a not-yet-written file and get a spurious 404. The single `on_started` call now fires only
**after** `create_request(...)` (and after the folder skeleton and `_runs` registration). Merged
via PR #8 (`abcecf9`).

This was the **first increment run through the full gated merge loop**: reviewer-authored test that
reproduced the race and failed on `main` → fix implemented by Cursor (Grok 4.6) → Review A
(diff-reviewer, Claude Opus 4-8) APPROVE + Review B (GPT-5.6 Sol) APPROVE → gate-integrity clean →
auto-merged (squash) when the required `gate` check went green.

## 2026-09-01 — Continuous integration (GitHub Actions)

Added `.github/workflows/ci.yml`. On pull requests targeting `main`, a **windows-latest** job
(the project is Windows-only and has Windows-specific tree-kill / process-group code paths that must
be exercised) installs the pinned dependencies — pip `requirements.txt` + `requirements-dev.txt`
(including the editable SDK and the `--no-binary mypy` line) and `npm ci` in `frontend/` — then runs
the full six-command gate, each as its own named step:

1. `ruff check`
2. `ruff format --check`
3. `mypy`
4. eslint (`npm run lint`)
5. tsc (`npm run typecheck`)
6. `pytest`

The six checks run with `if: ${{ !cancelled() && … }}` so a single CI run surfaces **every** failing
check at once (not one at a time), while remaining guarded on both install steps succeeding so a
setup failure hard-stops the job; any check failure fails the job. Versions are pinned explicitly
(Python **3.12**, Node **20** LTS) since the repo has no `.python-version` or Node engines pin. pip
and npm are cached via the setup actions.

### What the green CI check does NOT cover

Two gaps are inherent to the current test suite and are **not** exercised by CI (mirrored in
`docs/PROJECT_STATUS.md`):

- **Real environment-manager venv build.** `tests/core/test_env.py` mocks
  `find_python` / `create_venv` / `install`, so CI never builds a real per-workflow venv or runs pip
  into one. The real path (`python -m venv` + `pip install -e sdk`) was verified by hand during
  Task 6, not by CI.
- **Real-socket SSE streaming and frontend runtime behaviour.** The SSE tests use FastAPI's
  in-process `TestClient`, which buffers streamed responses — CI confirms event content, ordering,
  and stream close, but **not** live incremental delivery over a real socket (verified manually
  against a real uvicorn server). The frontend has **no unit-test runner**; CI covers it via eslint +
  tsc only (lint + types), not runtime behaviour (verified manually in a browser).

No tests are skipped, weakened, or disabled to make CI green — all 150 run.
