# Changes

A running log of notable changes outside the per-task build history.

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
