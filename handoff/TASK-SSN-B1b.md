# TASK-SSN-B1b — Run-settings controls in the launch form (approval mode + per-video budget)

Add two run-settings controls to the launch form and send them in the launch body (the backend accepts them from B1a). Make the supervisor-authored frozen tests green WITHOUT editing them (new cases in `frontend/src/components/RunLaunchForm.test.tsx`, the `describe("RunLaunchForm run settings")` block). Keep the existing RunLaunchForm tests green. Do NOT run `npm run build`.

Scope note / deferrals (do NOT build these here): the **voice picker** is deferred until B4 ships bundled voice presets and a voices list to choose from (the backend already accepts `voice`); the **scheduled-run + manual-approval warning** belongs to the scheduler-config UI, not this immediate-launch form. This increment is the two fully-backed controls only.

## Controls

1. **Approval mode** — a `<select>` labelled "Approval mode" with two options:
   - value `manual` — text like "Manual approval (approve before spending)" — the DEFAULT.
   - value `autonomous` — text like "Autonomous (no approval)".
   Map to `gates_auto`: `autonomous` -> `true`, `manual` -> `false`. The select must have an accessible name matching /approval/i (wrap it in the existing `<label className="field"><span className="field-label">Approval mode</span>...</label>` pattern).

2. **Per-video budget** — an optional `<input type="number">` labelled "Per-video budget (USD)" (accessible name matching /budget/i; use the existing field pattern; `min={0}` `step` a cent is fine). Empty = no cap. Placeholder e.g. "e.g. 6.00".

## Submit behaviour (`onSubmit` in RunLaunchForm.tsx)

- Compute `gates_auto = approvalMode === "autonomous"` and always include it in the `startRun` body.
- Per-video budget: if the field is non-empty, parse it; if it is not a finite number strictly greater than 0, set the form error to exactly "Per-video budget must be greater than 0." and RETURN without calling startRun (mirrors the backend's (0, 1000] rule client-side; the backend remains the authority). If the field is empty, OMIT `per_video_budget` from the body (do not send 0 or null).
- The `startRun` body becomes `{ params, video_count, concurrency, gates_auto, ...(budget set ? { per_video_budget: budget } : {}) }`.

## Types / api

- `frontend/src/types.ts`: extend `LaunchBody` (line ~200) with `gates_auto?: boolean;` and `per_video_budget?: number;` (both optional; leave `voice` out until the picker exists).
- `frontend/src/api.ts`: `startRun` forwards the body as-is, so likely no change is needed; touch it only if the type change requires it.

## Observability / design

- No `console.error` in any state. The controls reuse the existing `.field` / `.field-label` / `.field-input` design tokens (no new colours; no restyling of other views). Keep the existing Video count / Concurrency / param controls unchanged.

## Scope

- frontend/src/components/RunLaunchForm.tsx
- frontend/src/types.ts
- frontend/src/api.ts (only if needed)

Do NOT modify: any test, backend, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`.

## Constraints

- Workspace boundary; one paragraph is one line in Markdown.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `npm --prefix frontend run test -- --run src/components/RunLaunchForm.test.tsx` passes (the three new run-settings cases + all existing cases).
- `npm --prefix frontend run lint` and `npm --prefix frontend run typecheck` clean.
- Print the files you changed and a one-paragraph summary.
