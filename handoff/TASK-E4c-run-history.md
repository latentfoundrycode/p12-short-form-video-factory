# TASK E-4c — records/replay: past-run browsing + Replay (§8.6, mockup workflow-card → run detail)

## Goal (one sentence)
Let the user browse a workflow's past runs and open any one's record, and replay a run — so the
records/replay detail (E-4b) is reachable for history, not just the just-launched run.

## Why / design source
Today the app only shows a run's detail (`RunView` → `RunRecordView`) for a run it just launched
(`App.tsx` `activeRun`). There is no way to see a workflow's run history. `list_runs` + `fetchRuns`
+ the `RunList`/`RunSummary` types already exist (backend done). The approved mockup
(`docs/SFVF_UI_Mockup.html`) reaches a run's detail from a workflow card ("Review N videos") through
a list; this task implements that path with the existing house components. Frozen interface rule:
`.cursor/rules/30-frontend.mdc`. Stay consistent with `WorkflowGrid`/`WorkflowCard`/`RunView` and the
`index.css` tokens.

## What to implement (frontend only)

### 1. `RunsListView` (new `frontend/src/components/RunsListView.tsx`)
Given a `workflowId`, fetch `fetchRuns(workflowId)` and render the workflow's runs newest-first (the
API already sorts `run_id` desc). Each row shows: `run_id`, a status pill (reuse the
`RunView` status-pill mapping — extract/share or replicate the small helper), `started_utc`, and the
video count (`videos.length` with per-status breakdown optional). A row is clickable and calls an
`onOpenRun(runId)` prop. Handle loading / error / empty ("No runs yet.") states. A "Back" control
(prop `onBack`) returns to the workflows grid.

### 2. Navigation wiring (`App.tsx`)
Add a lightweight view state so the user can go: workflows grid → a workflow's runs list → a run's
detail, and back. Suggested: a `browsing: {workflowId} | null` state alongside `activeRun`.
- A workflow card raises "view runs" → `setBrowsing({workflowId})` → render `RunsListView`.
- `RunsListView` `onOpenRun(runId)` → `setActiveRun({workflowId, runId})` (opens the existing
  `RunView`, which shows `RunRecordView` for a terminal run).
- `RunView` `onClose` returns to wherever the user came from (the runs list if they were browsing,
  else the grid). Keep the existing launch→`activeRun` path working unchanged.

### 3. Workflow card affordance (`WorkflowCard.tsx` + `WorkflowGrid.tsx`)
Add a "Runs" (run history) button to each workflow card, consistent with its existing buttons; it
raises up to `WorkflowGrid` → `App` to open that workflow's runs list. Thread a new callback
(`onViewRuns(workflowId)`) through `WorkflowGrid` like the existing `onStarted`.

### 4. Replay (`RunView.tsx`)
On a TERMINAL run, add a "Replay run" button. It re-launches the SAME workflow with the run's
recorded params via `startRun(workflowId, { params: run.params, video_count: run.videos.length,
concurrency: 1 })`. On success (`run_id` returned) open the new run (raise an `onReplay(runId)` /
`onOpenRun` prop up to `App`, which sets `activeRun` to the new run). Surface the launch failure
cases already handled in `RunLaunchForm`/`startRun` (409 busy, 422 blocked/invalid) as an inline
error; do not crash. Disable the button while the replay request is in flight.

## Out of scope (do NOT build — later increment E-4d)
The Decisions panel (from `decision` events) and the Instructions-in-force panel (its backend record
field is not populated yet — needs a separate backend increment). "Your judgement" quality capture
(a write, later stage). Do not add a router library, a new tab, or any dependency.

## Constraints / do-nots
- Frontend only. Do NOT change any backend file, `app/`, `sdk/`, or any API. Do NOT add a
  dependency. Do NOT edit the mockup or docs.
- Keep `npm --prefix frontend run typecheck`, `run lint`, and `run build` all clean. Reuse existing
  `index.css` classes/tokens; add new ones only as needed, consistent with the house style.
- After building, DO NOT commit `app/web/.gitkeep` as deleted — the Vite build wipes it; leave it be
  (the supervisor restores it). Do not touch it.

## Scope
- `frontend/src/`

## Verify (from the worktree)
- `npm --prefix frontend run typecheck` → clean.
- `npm --prefix frontend run lint` → clean.
- `npm --prefix frontend run build` → succeeds.
- (The supervisor runs the full pytest gate and verifies the flow in-browser against seeded runs.)
