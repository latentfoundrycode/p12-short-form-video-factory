# TASK G-2 fixes (round 2) — restore block layout for the now-label/span quality fields

## Why
The a11y fix changed `.factor` (was a `<div>`) to a `<label>` and `.factor-q` (was a `<div>`) to a
`<span>` — both default to `display: inline`, so their `margin-bottom` (18px / 7px) has no layout
effect and the question/textarea/verdict spacing collapses (cramped vs the mockup). design-auditor
flagged this as a fidelity regression introduced by the fix.

## Scope
- `frontend/src/index.css`

## Exact change (`frontend/src/index.css` only)
On the existing `.factor` rule, add `display: block;`. On the existing `.factor-q` rule, add
`display: block;`. (Do not change their margins or any other property; only add the one `display`
declaration to each so the ported vertical spacing renders as in the mockup.)

## Verify (from the worktree)
- `cd frontend && npm run build && npm run stylelint` → clean.
- `npx prettier --check src/index.css` → clean.
