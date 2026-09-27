# TASK F2b-frontend — the main-tab WorkflowCard UI (completes F2)

Satisfies R-005/R-006/R-007/R-008/R-011 (UI), PRD §8.1. RED-first: the frozen test
frontend/src/components/WorkflowCard.test.tsx is RED (6 of 8). Read it first — it fixes the exact
state/outline/pill rules and the accessible text. Do NOT edit it.

## 1. types.ts — extend Workflow (F2a/F2b backend fields now consumed)
Add: `avg_cost_per_meter: Record<string, number>`, `runs_counted: number`, `archived: boolean`,
`last_run: { run_id: string; status: string; stage: { index: number; total: number; label: string } | null; progress: { done: number; total: number } | null } | null`.

## 2. index.css — add the missing house classes used by the mockup card (see docs/SFVF_UI_Mockup.html #v-workflows)
`.card-meters`, `.avg-label`, `.meter-val.none` (reuse existing `.meters/.meter/.meter-name/.meter-val/.meter-unit`, and the existing `.card.s-run/.s-done/.s-fail/.s-arch` + `.pill.run/.done/.fail/.idle`). Add no new class without a rule.

## 3. WorkflowCard.tsx — accept `seen: boolean` and render by this decision order (first match)
1. `workflow.archived` -> `className="card s-arch"`, pill "Archived", NO avg-cost block, foot shows ONLY the Runs button (label "Runs" is fine; no "Run workflow" button).
2. `!workflow.valid` (not archived) -> `card s-fail`, pill "Broken", list error problems (existing behaviour).
3. `last_run?.status === "running"` -> `card s-run`, pill "Running", a stage line from `last_run.stage`: "{index} / {total} — {label}" (+ optionally a second line from `progress` "{done} of {total}"). If stage is null, show a generic "Running" state line.
4. `last_run?.status` in {"failed","stopped-budget"} -> `card s-fail`, pill "Broken" (needs attention).
5. `last_run?.status` in {"complete","partial"} AND `!seen` -> `card s-done`, pill "Finished".
6. otherwise -> `card`, pill "Idle" (covers idle, user "stopped", and seen-cleared finished).
In every NON-archived state also render the average-cost block: `.card-meters` with an `.avg-label`
"Average per video · last 10 runs" and a `.meters` row of `.meter` cells from `avg_cost_per_meter`
(name + value); when `runs_counted === 0`, render a "No runs yet" treatment (e.g. `.meter-val none`).
Keep the Run workflow + Runs buttons for non-archived, non-broken states as today (Run hidden when broken).
No console.error; never render undefined/NaN/[object Object].

## 4. WorkflowGrid.tsx — seen-set + liveness
- Track a client-side `Set<string>` of workflow ids whose runs the user has opened; add the id in the
  existing `onViewRuns` path; pass `seen={set.has(workflow.id)}` to each `WorkflowCard`.
- While ANY card has `last_run?.status === "running"`, re-fetch `GET /api/workflows` on a ~3s interval
  so the running stage advances; stop polling when none are running. (Single-user local; keep it simple
  — a setInterval guarded by a "any running" check, cleared on unmount.)

## Done when
- `npm --prefix frontend run test` passes (incl. WorkflowCard.test.tsx), `npm --prefix frontend run lint`
  and `npm --prefix frontend run typecheck` clean.
- No new CSS class without a rule; composes from house classes; matches the mockup card.
- End with an `Assumed, not verified` list (or `none`).
