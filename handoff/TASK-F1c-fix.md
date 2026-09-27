# TASK F1c-fix — Settings tab: styling, mutation feedback, and default_concurrency consumption

Follow-up to F1c. Three reviewers (Review A, design-auditor FAIL, Review B REJECT) converged.
RED-first: new frozen tests are in place and RED —
`frontend/src/components/SettingsView.test.tsx` ("a failed save surfaces an error…",
"disables Save for a key until a value is entered") and
`frontend/src/components/RunLaunchForm.test.tsx` ("seeds the concurrency field from the stored
global default"). **Do NOT edit any test file.** Make them pass by changing implementation.

## Blocker 1 — the Settings screen renders unstyled (design-auditor)
`SettingsView.tsx` uses invented class names (`settings-sections`, `settings-secret-row/head/label/actions`,
`settings-form`, `settings-view`) that have NO CSS in `frontend/src/index.css`, so panels sit flush
and key rows collapse. FIX by composing from the existing house classes the other tabs use — do NOT
add new CSS. Study `frontend/src/components/LibraryView.tsx`, `ScheduleView.tsx`, `StatisticsView.tsx`
and `index.css`: wrap the panels in `stack` (flex, gap:16px); build each section as a `.panel` with a
`.panel-head` + `.eyebrow` header; use `.field` / `.field-label` / `.field-input` for inputs and
`.detail-actions` (or the mockup's `keyrow`) for the per-key row of input + buttons. The result must
match the house look with proper spacing.

## Blocker 2 — mutation failures are swallowed; no in-flight guard (all three reviewers)
`saveSecret` / `clearSecret` / `saveDefaults` are fired with `void` and never `.catch`. A failed
PUT/DELETE (locked-store 409, validation 400/422) gives no feedback and an unhandled rejection.
FIX (mirror LibraryView's `actionError` pattern):
- Add an `actionError: string | null` state; on a mutation rejection, set it from the error message
  and render it (e.g. a `.form-error` / `.card-state` near the action), do not leave it swallowed.
- Guard against double-submit: disable the row's Save/Clear (and the Save-defaults button) while its
  request is in flight.
- Disable a key's Save button while its input is empty/blank (so an empty PUT is never sent).
- The defaults number inputs: clearing a field must not silently become `0` (`Number("")===0`). Treat
  an empty/`NaN` field as "no change" (leave the draft at its loaded value) rather than storing 0.
- An env-locked field (`source === "env"`) is read-only; its `onChange` must not write the draft.
- On a successful save, refresh WITHOUT flashing the whole screen to the full "Loading settings…"
  block — keep the panels mounted and show an inline "Saving…"/disabled state (like the sibling views).

## Blocker 3 — default_concurrency is stored but never consumed (Review B / KP-029)
A user can set Default concurrency in Settings, see "Source: stored", and the next launch still starts
at 1. FIX by seeding the launch surfaces from the stored default (via `api.fetchSettings()` ->
`defaults.default_concurrency.effective`):
- `frontend/src/components/RunLaunchForm.tsx`: fetch settings on mount and use
  `defaults.default_concurrency.effective` as the INITIAL `concurrency` state (line ~506, currently
  `useState(1)`). The user can still change it before launch.
- `frontend/src/components/ScheduleView.tsx`: for a NEW entry (no `entry`), seed the initial
  `concurrency` (line ~54, currently `entry?.concurrency ?? 1`) from the same stored default; keep an
  existing entry's own saved value when editing.

## Advisory (fold in)
- Configured-key status pill: use `pill done` (green, the house ready/valid token), not `pill music`
  (amber). Missing stays `pill idle`.

## Done when
- `npm --prefix frontend run test` passes (all files), including the three new RED cases.
- `npm --prefix frontend run lint` and `npm --prefix frontend run typecheck` clean.
- No new CSS class without a rule; the screen composes from existing house classes.
- Frozen test files unmodified. End with an `Assumed, not verified` list (or `none`).
