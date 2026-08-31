# TASK-005-4 — Frontend: start a run, watch live progress, stop

## One-line task and why
Give the operator a way to start a generation request from a workflow card, watch its progress
live in the browser, and stop it — closing the Task 5 vertical (Architecture §6 frontend; §1.2/§3.3
SSE live progress; §15 the frontend holds no authoritative state, everything comes from the
backend). Final increment of Task 5. Scope is **live progress only**: NOT the polished per-video
record/detail view, gate-rendering UI, or quality UI (those are later tasks).

## The backend you are wiring to (already built and on main)
- `POST /api/workflows/{id}/runs` — body `{ "params": object, "video_count": int>=1, "concurrency":
  int>=1 }`. Returns **202** `{ "run_id": "..." }`; **409** if that workflow already has an active
  run; **422** `{ "reason": "..." }` if the env is blocked, or `{ "detail": "workflow is invalid" }`
  if the workflow is registry-invalid.
- `POST /api/workflows/{id}/runs/{run_id}/stop` — body `{ "mode": "graceful" | "hard" }`. 200
  `{ run_id, mode }`; 404 if not running.
- `GET /api/workflows/{id}/runs` — `{ "runs": [ { run_id, status, started_utc, ended_utc,
  videos:[{index,status}] } ] }`, newest first.
- `GET /api/workflows/{id}/runs/{run_id}` — the run detail: `{ run_id, workflow, started_utc,
  ended_utc, status, params, params_locked_utc, videos:[{index,status}], video_records:[...],
  budget, forecast }`. `status` ∈ `running | complete | partial | stopped | stopped-budget |
  failed`.
- `GET /api/workflows/{id}/runs/{run_id}/events` — **SSE** (`text/event-stream`). Each message is
  `data: <json>` where `<json>` is `{ "ts": str, "source": str, "event": {...} }`. On connect it
  **replays the whole history** (catch-up for late-join/refresh), then streams live, and the server
  **closes the stream when the run reaches a terminal status**. Event shapes (`event.t`): `stage`
  `{index,total,label}`, `log` `{level,msg}`, `cost` `{meter,unit,amount,note}`, `progress`
  `{family,done,total}`, `heartbeat` `{name,waiting_on}`, `step` `{name,key,label,status}`,
  `result` `{video,caption}`, plus others you can render generically.

## Current frontend (match its conventions exactly)
- React 19 + TypeScript (strict), Vite. No router — navigation is `useState` in `App.tsx`
  (`frontend/src/App.tsx`). **Do NOT add react-router or any dependency.**
- `frontend/src/api.ts` — typed `fetch` wrappers (see `fetchWorkflows`). Add run functions here.
- `frontend/src/types.ts` — shared types. Add run/event types here.
- `frontend/src/components/WorkflowCard.tsx` — has a **disabled** `Run workflow` button
  (`btn btn-primary btn-sm`). This is the start-run hook.
- `frontend/src/components/WorkflowGrid.tsx` — data-loading pattern to mirror (loading/ready/error,
  `useCallback`, cancellation flag in `useEffect`).
- `frontend/src/index.css` — existing classes to REUSE: `.panel/.panel-head/.panel-body`,
  `.btn/.btn-primary/.btn-ghost/.btn-sm`, `.pill` (+ `.run/.done/.fail/.warn/.idle`), `.dot`,
  `.card` (+ `.s-run/.s-done/.s-fail`), `.view/.on`, `.page-head/.page-title/.page-note`,
  `.card-foot`, `.st`. Add new CSS in `index.css` using the existing color tokens/variables already
  defined at the top of that file (match the palette; do not introduce new colors).

## What to build
1. **`api.ts` + `types.ts`:** add `startRun(id, body) -> { run_id } | { error }` (map 202/409/422 to
   a typed result the UI can branch on — surface the 409 "already running" and 422 reason as
   readable errors), `stopRun(id, runId, mode)`, `fetchRun(id, runId)`, `fetchRuns(id)`. Add the run
   detail, video-ref, and SSE-envelope types. The SSE URL is just a string the RunView builds.
2. **Start control on the card:** enable the `Run workflow` button (only when `workflow.valid`). On
   click, show a **minimal** launch form (an inline `.panel` or a small modal built from existing
   classes) with: `video_count` (number, default 1, min 1), `concurrency` (number, default 1, min
   1), and a `params` JSON `<textarea>` (default `{}`; validate it parses as an object before
   submit, show a clear inline error if not). Submitting calls `startRun`; on success switch the app
   to the **RunView** for that `run_id`; on 409/422 show the returned message and stay on the form.
   (Label the form clearly as a minimal launcher — the full provider-driven Run pop-up comes later.)
3. **`RunView` component** (new, `frontend/src/components/RunView.tsx`): props `{ workflowId, runId,
   onClose }`. On mount it (a) `fetchRun` for the initial status/params/videos, and (b) opens an
   `EventSource` on `/api/workflows/{workflowId}/runs/{runId}/events`. Render:
   - The overall run **status** (a `.pill` coloured by state) and the per-video statuses.
   - The **current stage** (from the latest `stage` event: `index/total — label`), tolerating a
     `total` that changes mid-run (§3.3 — never latch the first total).
   - A **live event feed**: a scrolling list of received events rendered readably by type (stage,
     log with level, cost, progress `done/total`, step, result). Newest-visible; auto-scroll is
     fine. This is the core live-progress value.
   - **Stop controls** while the run is active: a graceful **Stop** and a **Force stop** (hard)
     button calling `stopRun`; disable them once the run is terminal.
   - A **close/back** control (`onClose`) returning to the grid (mirrors the mockup's pseudo-tab red
     close button; a plain button is fine).
4. **Wire `App.tsx`:** add app-level state for an active run view `{ workflowId, runId } | null`.
   When set, render `RunView`; otherwise the grid. Starting a run sets it; closing clears it.

## EventSource reconnect gotcha — handle this explicitly (required behaviour)
The SSE endpoint **closes the HTTP stream when the run finishes**. A native `EventSource` treats a
closed stream as a dropped connection and will **auto-reconnect**, re-running the full catch-up —
an infinite loop of replays after completion. Required behaviour:
- On `EventSource.onerror` (fires when the server closes the stream), call `fetchRun`; if the status
  is **terminal**, `close()` the `EventSource` and render the final state — do **not** keep
  reconnecting. If the status is still `running` (a genuine transient drop), you may let it
  reconnect.
- Because every (re)connect replays the entire history, avoid duplicated log entries: rebuild the
  event list from the connection's replay (e.g. reset the list on `EventSource.onopen`, then append
  on `onmessage`) — or an equivalent dedupe. The visible list must equal the run's full history, not
  a doubled one, after a reconnect.
- Always `close()` the `EventSource` on component unmount (`useEffect` cleanup).

The net acceptance: opening RunView on a **running** run shows events arriving live and then a final
status when it ends (no reconnect loop); opening RunView on an **already-finished** run shows the
full history then the final status (pure replay); a browser refresh re-catches-up correctly.

## Testing / verification
There is no frontend unit-test runner in this project (the gate is lint + typecheck only), and
adding one is out of scope — do **not** add a test dependency. Instead:
- Keep `npm --prefix frontend run lint` and `npm --prefix frontend run typecheck` **clean** (strict
  TypeScript; no `any` leaks — type the API responses and events).
- Make the code structured and readable so behaviour can be verified in a real browser. The
  supervisor will verify live in a browser against a real uvicorn server (build → serve → start a
  stub run → watch live events → stop).

## Scope — files you may change
- `frontend/src/api.ts`, `frontend/src/types.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/WorkflowCard.tsx` (enable + wire the Run button / launch form; a small
  launch-form component may live in its own file under `frontend/src/components/`)
- `frontend/src/components/RunView.tsx` (new), and any small new component files under
  `frontend/src/components/`
- `frontend/src/index.css` (additive styles using existing tokens)

## Do NOT touch
- Anything under `app/`, `sdk/`, `tests/`, `docs/`, or `handoff/`. This is a frontend-only change.
- Do NOT add any dependency (no react-router, no SSE/polling/query/state libraries, no test runner).
- Do NOT build the polished per-video record/detail view, gate-rendering UI, or quality UI.
- Do NOT introduce new color values — reuse the CSS variables already in `index.css`.

## Gate — run all six before committing (worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
All must stay clean (pytest count unchanged at 149 — you add no Python). Also run
`npm --prefix frontend run build` and confirm it succeeds (the app is served from that build).

## Commit message (house style — imperative subject stating change and rationale)
```
Let the operator start, watch live, and stop a run in the browser, driving progress from the run's SSE event stream so the frontend holds no state of its own.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files changed, the commit hash, the final pytest count, and confirm
`npm --prefix frontend run build` succeeded.
