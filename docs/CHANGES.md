# Changes

A running log of notable changes outside the per-task build history.

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
