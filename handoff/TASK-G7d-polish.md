# TASK G-7d polish — three review nits (Learning tab)

Three small, non-blocking fixes from the G-7d review. Touch ONLY
`frontend/src/components/LearningView.tsx` and `frontend/src/index.css`.

## Fix 1 — colour the running/ready sub-line (design-auditor)
The mockup tints the sub-line amber while running and green when proposals are ready (row tint alone
today). Add to `frontend/src/index.css`, next to the existing `.lrn.s-run` / `.lrn.s-done` rules,
using the tokens (no raw colours):
```css
.lrn.s-run .li-sub {
  color: var(--amber);
}

.lrn.s-done .li-sub {
  color: var(--green);
}
```

## Fix 2 — left-align the review action buttons (design-auditor)
The review Accept/Reject row currently reuses `.card-foot` (centred, pushed to the bottom). The mockup
is a simple left-aligned row. In `index.css` add:
```css
.review-actions {
  display: flex;
  gap: 8px;
}
```
In `LearningView.tsx`, change the review panel's action-row wrapper from `className="card-foot"` to
`className="review-actions"`. (Only that one wrapper — do not touch the loading/error `.card-foot`.)

## Fix 3 — no dead-end on a zero-proposal run (diff-reviewer)
When a run returns 0 proposals the row shows "No changes proposed" in the `ready` state with NO action
button, so it is stuck until a full reload. In `LearningView.tsx`, in the row actions, add a case: when
`run.status === "ready"` AND `run.proposals.length === 0`, render a `btn btn-sm` **"Dismiss"** button
whose `onClick` resets that workflow's run to the idle run (the same `idleRun` reset used by the error
"Retry" button, keyed by `workflow.workflow_id`). Leave the `ready` + `proposals.length > 0` "Review"
button exactly as it is.

## Constraints
- ONLY the two files above. No new dependency. Do not touch `app/web/` or commit build output
  (restore `app/web/.gitkeep` if the build removes it).
- Keep it consistent with the existing token/format style; no raw colours; stylelint-clean.

## Verify (from `frontend/`)
- `npm run typecheck`, `npm run lint`, `npm run stylelint` → clean.
- `npm run build` → succeeds (do not commit the emitted `app/web/`).
