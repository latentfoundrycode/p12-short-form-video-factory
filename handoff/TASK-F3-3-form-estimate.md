# TASK F3-3 — run-form pre-launch cost estimate display (R-032 UI)

RED-first: frontend/src/components/RunLaunchForm.test.tsx has 2 RED estimate tests. Do NOT edit tests.
Consumes the F3-1 endpoint POST /api/workflows/{id}/estimate.

## 1. api.ts + types.ts
- types.ts: `EstimateOut { per_meter: Record<string, { amount: number; unit: string; kind: string }>; confidence: string; matches: number; video_count: number }`.
- api.ts: `fetchEstimate(workflowId: string, params: Record<string, unknown>, videoCount: number): Promise<EstimateOut>`
  — POST `/api/workflows/{workflowId}/estimate` body `{ params, video_count: videoCount }`; throw on !ok.
  **Signature order matters (frozen test asserts call[2] === videoCount): (workflowId, params, videoCount).**

## 2. RunLaunchForm.tsx — estimate panel
- On mount, and whenever `video_count` OR any param with `affects_cost === true` changes, call
  `fetchEstimate(workflowId, collectedParams, video_count)` DEBOUNCED (~300ms). Cancel/ignore stale
  responses (a later request must win). Guard against unmount.
- Render a cost panel (reuse house classes: a `.field`/panel area, or the `.meters`/`.meter` primitives)
  showing one line per meter in `per_meter`: the amount and its `unit` (e.g. "openrouter 0.42 usd"),
  plus a confidence label ("matched · {matches} runs" | "crude average" | "no data" for
  confidence matched/crude/none). Empty `per_meter` -> a "no estimate yet / no history" line.
- A failed estimate fetch must not break the form (show nothing or a subtle note; never throw).
- Do not block submit on the estimate; it is informational.

## Done when
- `npm --prefix frontend run test` passes (incl. the 2 RunLaunchForm estimate tests), lint + typecheck clean.
- Reuses house CSS classes (no new class without a rule).
- End with an `Assumed, not verified` list (or `none`).
