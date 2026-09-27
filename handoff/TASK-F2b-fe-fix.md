# TASK F2b-fe-fix — finished-green seen state (own in App, key by run_id) + keep Run on failed

Review B blockers. RED-first: the new/updated frozen tests in WorkflowGrid.test.tsx and
WorkflowCard.test.tsx are RED. Do NOT edit tests.

## Blocker 1 — R-007 green must survive tab nav and reset per run
`seen` currently lives in WorkflowGrid state, so opening the video list unmounts the grid and loses
it (the finished card goes green again), and it is keyed by workflow id, so a NEW run never re-greens.
Fix by lifting the state to App and keying it by run id:
- frontend/src/App.tsx: hold `const [openedRuns, setOpenedRuns] = useState<Set<string>>(() => new Set())`
  (App does not unmount on tab nav, so this survives). Pass `openedRuns={openedRuns}` to WorkflowGrid.
  Change the grid's onViewRuns handler to `(workflowId: string, runId: string | null) => { if (runId) setOpenedRuns(prev => new Set(prev).add(runId)); setBrowsing({ workflowId }); }`.
- frontend/src/components/WorkflowGrid.tsx: add prop `openedRuns: ReadonlySet<string>`; REMOVE the
  internal `seenWorkflowIds` state; compute per card `seen = wf.last_run != null && openedRuns.has(wf.last_run.run_id)`;
  change the prop/callback so opening Runs calls `onViewRuns(workflow.id, workflow.last_run?.run_id ?? null)`.
  Update onViewRuns's type to `(workflowId: string, runId: string | null) => void`.
- WorkflowCard passes the run id up when Runs is clicked (its onViewRuns prop signature follows the grid's).

## Blocker 2 — a failed (valid) workflow must keep the Run button
frontend/src/components/WorkflowCard.tsx resolvePresentation: `hideRun` must be true ONLY for
`archived` and `!valid` (invalid plug-in). For a VALID workflow whose last_run is failed/stopped-budget,
keep the Run workflow button (the run can be relaunched; the launch API only 409s while one is active).
Remove `hideRun: true` from the failed/stopped-budget branch.

## Done when
- npm --prefix frontend run test passes (incl. WorkflowGrid.test.tsx + WorkflowCard.test.tsx),
  lint + typecheck clean.
- End with an `Assumed, not verified` list (or `none`).
