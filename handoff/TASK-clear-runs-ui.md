# TASK — Runs list: per-run Delete + Clear-failed buttons (with confirm)

## Goal (one sentence)
Add a per-run Delete button and a "Clear failed" bulk button to the Runs list, each behind an inline
confirm, wired to the merged delete endpoints, refreshing the list on success.

## Why
The owner asked to declutter the Runs list. Backend endpoints (#100) already exist:
`DELETE /api/workflows/{id}/runs/{run_id}` (404/409/500) and
`DELETE /api/workflows/{id}/runs/clear-failed` → `{deleted: string[]}`.

## What to change

### 1. `frontend/src/api.ts`
Add two functions (match the existing throw-on-non-ok style):
```ts
export async function deleteRun(workflowId: string, runId: string): Promise<void> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}`,
    { method: "DELETE" },
  );
  if (response.ok) return;
  if (response.status === 409) throw new Error("This run is still active — stop it first.");
  throw new Error(`Could not delete run (${response.status})`);
}

export async function clearFailedRuns(workflowId: string): Promise<string[]> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(workflowId)}/runs/clear-failed`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(`Could not clear failed runs (${response.status})`);
  const data = (await response.json()) as { deleted: string[] };
  if (!Array.isArray(data.deleted)) throw new Error("Unexpected clear-failed response");
  return data.deleted;
}
```

### 2. `frontend/src/components/RunsListView.tsx` — the buttons + confirm
Import `deleteRun`, `clearFailedRuns`. Add state:
`confirmDeleteId: string | null`, `deletingId: string | null`, `confirmClear: boolean`,
`clearing: boolean`, `actionError: string | null`.

The "disposable" statuses (match the backend `_CLEARABLE`): `failed`, `stopped`, `stopped-budget`.
Compute `failedCount = runs.filter((r) => DISPOSABLE.has(r.status)).length`.

**Clear-failed (page-head):** next to the Back button, when `failedCount > 0` and not confirming,
show `<button className="btn btn-sm">Clear failed ({failedCount})</button>`. Clicking sets
`confirmClear = true`, which swaps in a confirm row: a note "Delete {failedCount} failed/stopped
runs? This can't be undone." + a `btn btn-sm btn-danger`-style **Clear** (disabled while `clearing`)
and a `btn btn-sm btn-ghost` **Cancel**. On Clear: `setClearing(true)`, `await
clearFailedRuns(workflowId)`, then reset confirm/clearing, clear `actionError`, and refresh the list
(bump the existing `reload` counter). On failure: set `actionError`, keep the confirm open,
`setClearing(false)`.

**Per-run Delete:** the run row is currently a single `<button className="run-row">`. Restructure so
the row is a `<div className="run-row">` containing (a) a clickable main area
`<button type="button" className="run-row-main" onClick={() => onOpenRun(run.run_id)}>` holding the
existing id + meta, (b) the status pill, and (c) a Delete control. Do NOT nest a button inside a
button. Behaviour of the Delete control:
- Default: `<button type="button" className="btn btn-sm btn-ghost">Delete</button>` →
  `setConfirmDeleteId(run.run_id)` (and clear any other confirm).
- When `confirmDeleteId === run.run_id`: show inline **Confirm** (`btn btn-sm`, disabled while
  `deletingId === run.run_id`) + **Cancel** (`btn btn-sm btn-ghost`). Confirm →
  `setDeletingId(run.run_id)`, `await deleteRun(workflowId, run.run_id)`, then on success clear both
  confirm/deleting and refresh the list; on failure set `actionError`, clear `deletingId`, keep the
  row's confirm open. Cancel → `setConfirmDeleteId(null)`.
- Clicking Delete / Confirm / Cancel must NOT trigger the row's open navigation (they are siblings of
  `.run-row-main`, not inside it, so this is automatic once restructured).
- A running run's row still shows Delete, but the backend returns 409 → the error surfaces via
  `actionError` ("This run is still active — stop it first."). That's acceptable; do not special-case.

Show `actionError` (when set) as a `.form-error` near the top of the list panel. After any successful
delete/clear, also clear `confirmDeleteId`/`confirmClear`.

### 3. `frontend/src/index.css` (only if needed)
`.run-row` is currently styled as a button; when it becomes a `<div>` with a `.run-row-main` button
inside, keep the visual identical — reuse the existing `.run-row` / `.run-row-main` rules, moving the
hover/cursor to `.run-row-main` if the row no longer is the button. Add a `.run-row-actions` flex
wrapper (`display:flex; gap:6px; align-items:center;`) for the pill + delete control if helpful. If
no `.btn-danger` exists, use the plain `.btn` for the destructive confirm (do not invent a red button
unless a `--red`-based rule is trivial); keep it minimal and consistent with existing variables.

## Constraints / do-nots
- Touch ONLY `frontend/src/api.ts`, `frontend/src/components/RunsListView.tsx`,
  `frontend/src/index.css`.
- Do NOT write into `app/web/` or touch `app/web/.gitkeep`; do not commit built assets.
- No `any`; keep the React 19 idiom. Keep `npm run lint` / `npm run typecheck` clean.
- The whole-row open navigation must keep working; Delete/Confirm/Cancel must not open the run.

## Design follow-up (SECOND delegation — four small polish items)
Your first implementation passed design review with no blockers and works end-to-end. Apply these:
1. **Destructive-confirm consistency:** give the per-row **Confirm** button `className="btn btn-sm
   btn-danger"` (currently neutral `btn btn-sm`) so both destructive confirmations (per-run Confirm
   and bulk Clear) read with the same red-tinted weight.
2. **Focus the Confirm control when a confirm opens** (a11y — otherwise focus falls to `<body>`).
   Add `autoFocus` to the per-row **Confirm** button and to the bulk **Clear** button (both only
   render while their confirm is open, so `autoFocus` fires on open). No refs needed.
3. **Prompt vertical alignment:** in `index.css`, add `.clear-runs-confirm .page-note { margin-top:
   0; }` so the confirm sentence sits centered with the Clear/Cancel buttons (the base `.page-note`
   has `margin-top: 3px`).
4. **Head wrap on narrow width:** add `flex-wrap: wrap; gap: 8px;` to `.page-head` (or, if that risks
   disturbing other pages, add `flex-wrap: wrap;` to `.page-head-actions` only) so the open bulk-clear
   confirm row doesn't crowd the title on a narrow viewport.

Touch only `RunsListView.tsx` and `index.css`. Keep lint/typecheck/build clean.

## Scope
- `frontend/src/api.ts`
- `frontend/src/components/RunsListView.tsx`
- `frontend/src/index.css`

## Verify (from the worktree)
- `cd frontend && npm run lint` → clean.
- `cd frontend && npm run typecheck` → clean.
- `cd frontend && npm run build` → succeeds (do NOT commit the `app/web/` output).
- `cd frontend && npm run stylelint` and `npx prettier --check src/components/RunsListView.tsx src/api.ts`
  → clean for the files you changed.
