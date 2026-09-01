# TASK-CI-ACTION-BUMP — Bump CI action majors off the deprecated Node-20 runtime

## One-line task and why
GitHub is deprecating the Node-20 *action runtime*. Our CI pins `actions/checkout@v4`,
`actions/setup-node@v4`, and `actions/setup-python@v5`, which declare that deprecated runtime
(GitHub currently force-runs them on Node 24 and warns). Bump each to its current Node-24 major so
the warning clears and the workflow keeps working after Node 20 is removed from runners.

This is a **CI-config-only** increment — there is no product code change and no unit test. It is
validated by this PR's own CI run: the required `gate` check runs the bumped workflow, so a green
`gate` proves the new action versions work.

## The change (the ONLY change)
In `.github/workflows/ci.yml`, bump exactly these three `uses:` action majors:

- `actions/checkout@v4`      → `actions/checkout@v5`
- `actions/setup-node@v4`    → `actions/setup-node@v7`
- `actions/setup-python@v5`  → `actions/setup-python@v6`

(These are the current Node-24 majors, verified 2026-09-01.)

## Must NOT change — keep the gate exactly as strong
Change **only** the three `uses:` version tags above. Do NOT alter anything else in the workflow:

- Keep all six check steps (`ruff check`, `ruff format --check`, `mypy`, `npm run lint`,
  `npm run typecheck`, `pytest`) and both install steps.
- Keep every `if: ${{ !cancelled() && steps.deps_py.conclusion == 'success' && steps.deps_fe.conclusion == 'success' }}` guard verbatim.
- Keep `permissions: contents: read`, the `concurrency` block, and the `cache:` / `cache-dependency-path:` settings.
- Keep **`node-version: "20"`** on setup-node unchanged — that is the Node the frontend builds with
  (the app runtime), which is deliberate and SEPARATE from the action-runtime deprecation. Do not
  touch it. Keep `python-version: "3.12"`.
- Do NOT add `continue-on-error`, do NOT skip/drop/rename any step or job, do NOT weaken any check.

## Scope — files you may change
- `.github/workflows/ci.yml` (only the three `uses:` version tags)

## Do NOT touch
- Any other file. No source (`app/`, `sdk/`, `frontend/`), no tests, no `docs/`, no `handoff/`.
- Do not add dependencies. Do not restructure the workflow.

## Acceptance
- The diff is exactly three changed lines (the three `uses:` version tags); nothing else differs.
- The PR's required `gate` check runs the bumped workflow and passes.

## Commit message (house style — imperative subject stating change and rationale)
```
Bump CI action majors to their Node-24 versions (checkout v5, setup-node v7, setup-python v6) so the workflow leaves the deprecated Node-20 action runtime.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files you changed and the commit hash.
