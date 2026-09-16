# TASK — H-4: gate UI (surface a pending gate in the live run view)

## Goal (one sentence)
When a run is parked at a gate, show it in the live Run view with the right decision surface —
approval, choice, or selection (a grid of item images with keep/redo) — and submit the user's answer
to the gate API, so the run continues.

## Background (already built)
- `GET /api/workflows/{id}/runs/{run_id}/gates` -> `{"gates": [{video, video_index, token, family,
  shape, prompt, payload?, options?, items?, on_bypass?}]}` (only pending gates).
- `POST /api/workflows/{id}/runs/{run_id}/gates` with `{video, token, decision}` writes the answer.
  Decision shapes: approval -> `{"choice": "approve"|"reject"}`; choice -> `{"choice": "<option>"}`;
  selection -> `{"choice": "approve"|"reject", "keep": [ids], "redo": [ids], "note": str}`.
- `RunView.tsx` already holds the live SSE `events` and renders the ACTIVE run layout
  (`RunStatusPanel` + live feed) when `!isTerminalStatus(run.status)`.
- `runFileUrl(workflowId, runId, path)` builds a file URL; a selection item's `artifact` is a path
  relative to its video dir, so its image src is `runFileUrl(workflowId, runId, `${gate.video}/${item.artifact}`)`.

## What to change

### 1. `frontend/src/types.ts`
```ts
export type PendingGate = {
  video: string;
  video_index: number;
  token: string;
  family: string;
  shape: "approval" | "choice" | "selection";
  prompt: string;
  payload?: unknown;
  options?: string[] | null;
  items?: { id: string; label?: string; artifact?: string }[] | null;
  on_bypass?: string | null;
};
```

### 2. `frontend/src/api.ts`
```ts
export async function fetchPendingGates(workflowId: string, runId: string): Promise<PendingGate[]> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/gates`,
  );
  if (!response.ok) throw new Error(`Could not load gates (${response.status})`);
  const data = (await response.json()) as { gates: PendingGate[] };
  if (!Array.isArray(data.gates)) throw new Error("Unexpected gates response");
  return data.gates;
}

export async function submitGate(
  workflowId: string, runId: string, video: string, token: string, decision: unknown,
): Promise<void> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/gates`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video, token, decision }) },
  );
  if (!response.ok) throw new Error(`Could not submit decision (${response.status})`);
}
```

### 3. New `frontend/src/components/GatePanel.tsx`
A component `GatePanel({ workflowId, runId, gateEventCount, onResolved })`:
- State: `gates: PendingGate[]`, `status: "loading" | "ready" | "error"`, `error`, `submitting`,
  `submitError`, and per-selection local UI state (`redo: Set<string>` of item ids marked to redo,
  `note: string`).
- Fetch pending gates via `fetchPendingGates` on mount and whenever `gateEventCount` changes (a new
  gate arrived on the SSE stream) and after a successful submit. Guard with a cancelled flag.
- Render nothing (return `null`) when there are no pending gates.
- Otherwise render the FIRST pending gate in a `.panel` (eyebrow "Decision needed", a `.gate-title`
  with `gate.prompt`). Reset the per-selection `redo`/`note` when the shown gate's token changes.
  By shape:
  - **approval**: an **Approve** (`btn btn-primary btn-sm`) and a **Reject** (`btn btn-sm btn-ghost`)
    button. If `gate.payload` is present, show it read-only in a `.diff`/`.diff-body` (JSON-stringified,
    2-space) like the learning-proposal panel, so the user sees what they're approving.
  - **choice**: one `btn btn-sm` per `gate.options`, each submitting `{choice: <option>}`.
  - **selection**: a `.gate-items` grid — one card per `gate.items[]` with, when `item.artifact`,
    an `<img className="gate-item-img" src={runFileUrl(workflowId, runId, `${gate.video}/${item.artifact}`)}
    alt={item.label ?? item.id}>`, the `item.label ?? item.id`, and a toggle to mark it **Redo**
    (default = keep; toggled items go to `redo`). A `<textarea className="field-input field-textarea">`
    for an optional note. An **Approve** button submits `{choice:"approve", keep: <ids not in redo>,
    redo: <ids in redo>, note}`, and a **Reject** button submits `{choice:"reject", note}`.
- Submit via `submitGate(...)`; on success clear the per-selection state, call `onResolved()` (lets the
  parent refresh) and refetch pending gates (the answered gate drops off). On failure set `submitError`
  (shown via `.form-error`), keep the panel open. Disable the buttons while `submitting`.

### 4. `frontend/src/components/RunView.tsx`
- Compute `const gateEventCount = events.filter((e) => e.event.t === "gate").length;`
- In the ACTIVE branch (the `run-layout` div, when NOT terminal), render `<GatePanel workflowId={workflowId}
  runId={runId} gateEventCount={gateEventCount} onResolved={() => { void fetchRun(workflowId, runId).then(setRun); }} />`
  ABOVE the `RunStatusPanel` (a blocking decision is the most important thing to show). Do not change
  the terminal branch.

### 5. `frontend/src/index.css`
Add minimal styles: `.gate-title` (like `.launch-title`), `.gate-items` (a responsive grid:
`display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap:12px;`), `.gate-item`
(a `.surface-2`/`--line` bordered card, `padding`, `border-radius:var(--r)`), `.gate-item-img`
(`width:100%; height:auto; border-radius:var(--r); background:var(--surface-2)`), and a small
`.gate-item.redo` accent (e.g. `border-color: var(--red)`) for a redo-marked item. Reuse existing
classes/variables; keep it consistent with the visual system.

## Constraints / do-nots
- Touch ONLY `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/components/GatePanel.tsx`
  (new), `frontend/src/components/RunView.tsx`, `frontend/src/index.css`.
- Do NOT write into `app/web/` or touch `app/web/.gitkeep`; do not commit built assets.
- No `any`; React 19 + hooks idiom. Keep `npm run lint` / `npm run typecheck` clean.
- The submit POST is CSRF-safe (same-origin); no extra headers needed beyond Content-Type.

## Design follow-up (SECOND delegation — three polish fixes)
Your first implementation passed design review and works end-to-end. Apply these:
1. **Redo checkbox label:** in `GatePanel.tsx`, the Redo toggle's text uses `<span className=
   "field-label">Redo</span>` (faint 10px uppercase). Every other `.field-check` in the app uses a
   plain `<span>Redo</span>` at body size — change it to a plain `<span>Redo</span>` so the affordance
   reads clearly and matches the other checkboxes.
2. **Surface a gate-load error:** currently `if (!gate) return null` short-circuits before the
   `.form-error` can render, so a `fetchPendingGates` failure while the run is parked shows nothing.
   Before the `if (!gate) return null`, add: when `status === "error"`, return a small `.panel` with
   the eyebrow "Decision needed" and the `error` message in a `.form-error` (so a load failure is
   visible on a parked run). Keep returning `null` only when the fetch succeeded and there are no
   pending gates.
3. **Image aspect:** in `index.css`, give `.gate-item-img` a consistent thumbnail — set
   `aspect-ratio: 1 / 1; object-fit: cover; max-height: 220px;` and change its `background` to a
   distinct placeholder tone (`var(--surface)` instead of `var(--surface-2)`) so mixed-aspect
   artifacts don't produce ragged card heights and the placeholder is visible.

Touch only `GatePanel.tsx` and `index.css`. Keep lint/typecheck/build clean.

## Scope
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/components/GatePanel.tsx`
- `frontend/src/components/RunView.tsx`
- `frontend/src/index.css`

## Verify (from the worktree)
- `cd frontend && npm run lint` → clean.
- `cd frontend && npm run typecheck` → clean.
- `cd frontend && npm run build` → succeeds (do NOT commit the `app/web/` output).
- `cd frontend && npm run stylelint` and `npx prettier --check src/components/GatePanel.tsx
  src/components/RunView.tsx src/api.ts src/types.ts` → clean for the files you changed.
