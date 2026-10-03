# TASK-102: Launch form — chassis controls, decimal point, remembered values, last-known options (F3-6b)

## Objective
The run launch form (`RunLaunchForm`) gains the remaining chassis settings of the requirements document §8.2 and four robustness behaviours: a per-run "Dry run" checkbox, a "Parallel steps per video" field seeded from the Settings default, a video-count cap where the workflow declares a maximum, locale-independent decimal entry for `number` params (point only), per-workflow memory of the last successfully launched values, and a last-known option list when a provider options fetch fails. The backend side already shipped in TASK-101: `POST /api/workflows/{id}/runs` accepts `dry_run` and `step_concurrency`, rejects a `video_count` above the workflow's `max_videos` with 422, and `GET /api/workflows` exposes `max_videos` per workflow. This increment is the frontend half, so the owner can set each of these from the form end to end.

Satisfies:
- R-019 — If the provider cannot be reached, the last-known option list is offered with a note (fallback to manual entry).
- R-021 — Decimal values use a point regardless of regional settings.
- R-023 — Number of videos is capped where the workflow declares a maximum.
- R-027 — Chassis setting: Parallel steps per video (default 1).
- R-028 — Chassis setting: Dry run (fake assets, no spending) selectable per run from the form.
- R-030 — Values used last time are remembered per workflow and pre-filled when the form is reopened.

**Methodology: RED-first.** The supervisor wrote the frozen contract test `frontend/src/components/RunLaunchForm.chassis.test.tsx` before this brief. 13 of its 21 tests fail today; that is intended. Your job is to make all 21 pass by changing implementation files only. Do not edit, add, rename, or delete any test file or test setup file (including `frontend/src/test/setup.ts`). The frozen test is the traceability record for every requirement above (its header and `describe` titles name each R-ID), so you do not write tests in this increment.

## Scope
Files and directories you may create or modify:
- frontend/src/components/RunLaunchForm.tsx
- frontend/src/components/WorkflowCard.tsx
- frontend/src/types.ts
- frontend/src/api.ts
- frontend/src/index.css

Do not modify anything else. `frontend/src/index.css` only if a class is genuinely needed; prefer the existing `.field`, `.field-label`, `.field-input`, `.field-help`, `.field-check`, `.form-error` classes. (The build plan names `frontend/src/styles.css`; that file does not exist — the stylesheet is `frontend/src/index.css`.) `frontend/src/api.ts` probably needs no change, because the `startRun` body type lives in `types.ts`; touch it only if the types require it.

## Out of scope
- .env and anything under secrets/
- CI configuration
- docs/ and handoff/ (except one-line appends to `docs/BUILDER_NOTES.md`, see Constraints)
- Every test file (`*.test.tsx`, `*.test.ts`) and `frontend/src/test/setup.ts`
- All backend code (`app/`, `sdk/`, `workflows/`); `app/web/` (build output)
- The "Per-video budget (USD)" field: leave it exactly as it is (still `type="number"`, still sent as `per_video_budget`). TASK-104 replaces it.
- File-type params (TASK-106), the read-only running view (TASK-105), budget lines (TASK-104)

## Context

### Applicable rules (already in force for you)
- `.cursor/rules/30-frontend.mdc`
- `.cursor/rules/minimal-code.mdc`
- `.cursor/rules/workspace-boundary.mdc`

There is no approved mockup for the launch form and no `docs/design/DESIGN.md`; match the existing form's markup and classes. There is no `vercel-interface.mdc` or `secure-coding.mdc` in this repo, and no documented ASVS level or observability section.

### Trust boundary
localStorage is untrusted input: another tab, an older app version, or a hand edit can leave anything there. Every value read back from `sfvf.launchForm.<id>` or `sfvf.providerOptions.<source>` must be shape-checked before use; a value of the wrong type is ignored, never rendered or sent as-is. Nothing secret is stored (launch params, counts, voice id, option lists only).

### Backend contract (TASK-101, `app/api/runs.py` lines 91-117, `app/api/workflows.py` line 128)
```python
class LaunchBody(BaseModel):
    params: dict[str, Any]
    video_count: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    gates_auto: bool = False
    per_video_budget: float | None = None
    voice: str = ""
    dry_run: StrictBool = False
    step_concurrency: int | None = None   # int >= 1, bool rejected; None -> Settings default
```
`WorkflowOut.max_videos: int | None = None`. A `video_count` above `max_videos` gets a 422 from the server; the form must catch it first.

### Frontend as built
- `frontend/src/types.ts`: `Workflow` (lines 42-55) has no `max_videos`. `LaunchBody` (lines 242-249) is the `startRun` body type and lacks `dry_run` / `step_concurrency`:
  ```ts
  export type LaunchBody = {
    params: Record<string, unknown>;
    video_count: number;
    concurrency: number;
    gates_auto?: boolean;
    per_video_budget?: number;
    voice?: string;
  };
  ```
  `SettingsDefaultKey` already includes `"default_step_concurrency"`; `SettingsData.defaults` is `Record<SettingsDefaultKey, SettingsDefaultField>` with `effective: number`.
- `frontend/src/api.ts`: `export async function startRun(id: string, body: LaunchBody): Promise<StartRunResult>`; `export async function fetchProviderOptions(source: string): Promise<ProviderOption[]>` (throws on failure); `export async function fetchSettings(): Promise<SettingsData>`.
- `frontend/src/components/RunLaunchForm.tsx`:
  - `type RunLaunchFormProps = { workflowId: string; workflowName: string; params: Param[]; onStarted: (runId: string) => void; onCancel: () => void; }` (lines 14-20).
  - `seedValue` (34-53), `initialValues` (55-61), `collectParams` (69-138) and `costParams` (140-191) handle `number` params with `Number(text)`.
  - `RegistryOptionsField` (230-390) fetches `options_from` lists; on failure (lines 272-302) it renders a manual `<input type="text">` with the help line `Couldn't load options — enter the value manually.`; it has a dedicated loading branch (P-9c) that must keep working.
  - `ParamField` `case "number"` (479-498) renders `<input type="number">` with `min`/`max`/`step` from the param.
  - Settings seeding effect (655-680): `fetchSettings` is reached through `import("../api")` and a typeof check, because `RunLaunchForm.loading.test.tsx` mocks `../api` with only `startRun`, `fetchProviderOptions`, `fetchVoices`. **Do not import `fetchSettings` statically** — that test would break. Read `default_step_concurrency` in that same load.
  - `onSubmit` (698-748) validates, then calls `startRun`; success is `isStartRunOk(result)`.
  - Chassis controls JSX (767-841): Video count, Concurrency, Approval mode (`manual` / `autonomous` → `gates_auto`), Per-video budget, Voice. Errors render as `<div className="form-error">`.
- `frontend/src/components/WorkflowCard.tsx` renders `<RunLaunchForm ...>` at lines 197-208 without a max.
- `frontend/src/test/setup.ts` clears localStorage after every test (supervisor commit 9685c424), so remembered values do not leak between tests.

### Queries the existing frozen tests use (your labels must keep them unambiguous)
- `RunLaunchForm.test.tsx` finds the count field with `getByLabelText(/number of videos|video count|videos/i)`, concurrency with `findByLabelText("Concurrency")`, the budget with `getByRole("spinbutton", { name: /budget/i })`, approval with `getByRole("combobox", { name: /approval/i })`, voice with `getByRole("combobox", { name: /voice/i })`, and on options-fetch failure `findByRole("textbox", { name: /Model/ })` plus `getByText(/manual/i)` (must match exactly one element).
- The chassis test uses `getByLabelText(/video count/i)`, `/^concurrency/i`, `/parallel steps/i`, `/ratio/i`, `/^topic/i`, `getByRole("checkbox", { name: /dry run/i })`, `getByRole("combobox", { name: /model/i })`.
- Therefore no new label or text inside a new `<label>` may match `/videos/i`, `/^concurrency/i`, `/budget/i`, `/approval/i`, `/voice/i`; and no new visible text other than the existing manual-fallback line may contain the word "manual".

## Diagrams
None. The project has no diagram index (the build plan sets `Diagrams: none` for every increment).

## Requirements

### Types and wiring
1. `Workflow` gains `max_videos: number | null`. `LaunchBody` gains `dry_run?: boolean` and `step_concurrency?: number`; existing fields are unchanged.
2. `RunLaunchFormProps` gains `maxVideos?: number | null` (absent or null = no cap). `WorkflowCard` passes `maxVideos={workflow.max_videos ?? null}`.

### R-028 Dry run
3. A native checkbox labelled "Dry run" (label associated with the input, operable by keyboard), unchecked by default. Checked → the launch body has `dry_run: true`; unchecked → `dry_run: false` (or omitted).

### R-027 Parallel steps per video
4. An integer field labelled "Parallel steps per video", `type="number"`, `min` 1, step 1, initial value 1, then seeded from `settings.defaults.default_step_concurrency.effective` when the Settings load succeeds (a failed or missing Settings load keeps 1).
5. The launch body carries the value as `step_concurrency` (an integer).
6. A value below 1, a non-integer, or an empty field blocks submit: `startRun` is not called and a `.form-error` appears whose text contains "Parallel steps".

### R-023 Video count cap
7. When `maxVideos` is a number, the "Video count" input has `max={maxVideos}`; otherwise it has no `max` attribute at all.
8. A count above `maxVideos` blocks submit: `startRun` is not called and a `.form-error` appears whose text contains the cap number (e.g. "This workflow allows at most 3 videos per request."). Exactly the cap is allowed.
9. Pitfall: jsdom (like browsers) runs native constraint validation when the submit button is clicked, unless the form opts out; a violated `min`/`max` attribute then cancels the submit event, so `onSubmit` never runs and the required `.form-error` never appears. Whatever you do, the app's own `.form-error` must be what the user sees for requirements 6, 8 and 12.

### R-021 Decimal point for `number` params
10. A param of `type: "number"` renders as `<input type="text" inputMode="decimal">` with its label still associated (`getByLabelText` must find it). The default shows with a point: default `0.5` → value `"0.5"`.
11. Input such as `"1.5"`, `"10"`, `"-2"` submits as the JSON number (`1.5`, `10`, `-2`) regardless of OS locale.
12. A value containing a comma (e.g. `"1,5"`) blocks submit with a `.form-error` whose text mentions "point" (e.g. "Ratio: use a point (.) as the decimal separator."). Any other text that is not a finite decimal number (e.g. `"abc"`, `"Infinity"`) blocks submit with an error naming the param. Empty keeps today's behaviour (omitted if optional, "is required." if required).
13. The param's declared `min` / `max`, which the old `type="number"` input enforced natively, are still enforced: a value outside them blocks submit with a `.form-error` naming the param and the bound.
14. `costParams` (the estimate input) applies the same point-only parsing: a value it cannot parse is left out, never sent as `NaN` or as a comma-parsed number.
15. The integer chassis fields (Video count, Concurrency, Parallel steps per video) stay `type="number"`. The Per-video budget field is unchanged.

### R-030 Remembered values per workflow
16. After a successful start only (`isStartRunOk(result)` true), store the submitted values as JSON under the localStorage key `sfvf.launchForm.<workflowId>` (the id verbatim): `params`, `video_count`, `concurrency`, `step_concurrency`, the approval mode (as `gates_auto` or the mode string), `voice`, `dry_run`. A failed start (an error result or a thrown error) stores nothing. The per-video budget is **not** remembered.
17. When the form mounts, it is pre-filled from that key, and the remembered values are already present on the **first render**. The frozen tests assert them synchronously right after `render`, with no await.
18. Each remembered field is validated on its own and ignored if invalid. Counts must be integers ≥ 1, never booleans. `dry_run` must be a boolean, `voice` a string, `params` a plain object. An ignored field falls back to its normal default. A remembered video count above the current `maxVideos` is also ignored.
19. Remembered params: a key that the current `params` do not declare is ignored. A declared param that is absent from the remembered map keeps its normal seed. A remembered value whose type does not fit the param's current type is ignored and the seed is used, for example a string for a multiselect, or a non-string for a text, select or decimal field.
20. Remembered values win over the Settings-seeded defaults. When the async Settings load finishes, it must not overwrite a remembered `concurrency` or `step_concurrency`. It still seeds any of the two that were not remembered, e.g. a stored object with `concurrency` but no `step_concurrency`.
21. A remembered voice that is not in the loaded voice list is dropped, and the default voice `""` is used. This includes the case where the voice list fails to load.
22. Memory is per workflow: values saved for `wf` never pre-fill the form for `other`.
23. Every localStorage access (`getItem`, `setItem`, and anything else) is wrapped in try/catch. Corrupt JSON, a non-object payload, or a storage whose `getItem` / `setItem` throws falls back to the defaults. The form renders, submit still calls `startRun`, and nothing is logged with `console.error`.

### R-019 Last-known options
24. On every successful `options_from` fetch, store the returned option list as JSON under `sfvf.providerOptions.<source>`, with the source verbatim, e.g. `sfvf.providerOptions.sfvf.models:video`. Use try/catch, as in requirement 23.
25. When a fetch fails and a stored list exists for that source, render the normal ready-state control from the stored list. For a select this is a `<select>`, still labelled with the param label, with the existing `(not configured)` and `(removed)` handling; for a multiselect it is the checkboxes. Add a `.field-help` line whose text contains "last known", e.g. "Couldn't reach the provider — showing the last known options."
26. A stored list is used only if it is an array of objects with string `id`, string `label` and boolean `configured`. Anything else counts as no stored list.
27. With no usable stored list, today's manual fallback is unchanged: the same text input and the same help text, `Couldn't load options — enter the value manually.`
28. While a fetch is in flight, the existing loading state (P-9c) is unchanged. Do not show the stored list during loading.

## Acceptance criteria
- [ ] All 21 tests in `frontend/src/components/RunLaunchForm.chassis.test.tsx` pass, unmodified.
- [ ] Every other frontend test passes unmodified, including `RunLaunchForm.test.tsx`, `RunLaunchForm.loading.test.tsx`, `WorkflowCard.test.tsx`, `WorkflowGrid.test.tsx`, `SettingsView.test.tsx`, `LibraryView.test.tsx`, `VideoDescription.test.tsx`, `src/test/smoke.test.tsx`. The test set is the same before and after: no test added, removed, skipped, or edited.
- [ ] `npm --prefix frontend test -- --run` passes.
- [ ] `npm --prefix frontend run lint` passes with no new suppressions. An `eslint-disable` comment is allowed only with a one-line reason, following the existing ones in this file.
- [ ] `npm --prefix frontend run typecheck` passes.
- [ ] If `frontend/src/index.css` was touched: `npm --prefix frontend run stylelint` passes.
- [ ] Each Satisfies requirement (R-019, R-021, R-023, R-027, R-028, R-030) is fully met as written above, with no placeholder, stand-in, or "coming later" text. The trace is the frozen chassis test, which names each R-ID in its header and `describe` titles.
- [ ] Every new control has an associated label and is keyboard-operable. The Dry run checkbox is a native `<input type="checkbox">`.
- [ ] No `console.error` is emitted in the happy path. The existing test "logs no console.error in the happy path" stays green.

## Constraints
- Do not add dependencies.
- Do not read or write any file outside this workspace (the folder you were started in). Everything you need is inside it; everything you produce goes inside it.
- If the brief, the rules, or the tooling got in your way — an instruction that contradicted another, a check that fired wrongly, a step that cost time for no reason — append one dated line describing it to `docs/BUILDER_NOTES.md`. Do not try to fix the tooling. Do the same for anything you learned about a defect or a pitfall (a cause you found, a platform quirk that cost you a round): one dated line, so the supervisor can carry it forward.
- In any Markdown you write, never break a line inside a paragraph or a list item; one paragraph is one line. Line breaks only between blocks.
- Any console process your code launches on Windows is created windowless (`creationflags=subprocess.CREATE_NO_WINDOW` in Python — `0` on other platforms; `windowsHide: true` in Node). Capturing output does not prevent the window. A window is allowed only when it serves the user (they watch it or type into it); then write the reason at the call site as `windowless: visible-ok <reason>`. A spawn that needs a process group for a `CTRL_BREAK` stop is hidden only with a test of the stop path. (This increment should launch no processes.)
- Do not refactor code outside the scope, even if it looks wrong.
- Follow existing conventions in the files you touch: function components, `className` strings from the existing stylesheet, `useEffect` cleanup with an `ignore` / `cancelled` flag, error text set via `setFormError`.
- Prefer reuse over new code — existing helpers, the standard library, native platform features, already-installed dependencies — and write the minimum that meets the acceptance criteria (the frozen `minimal-code.mdc` is in force). This never overrides a security, observability, or accessibility requirement stated above.
- Do not edit any test file or `frontend/src/test/setup.ts` (RED-first: the tests are the frozen contract). If you believe a frozen test is wrong or contradicts this brief, stop and report it in your summary instead of working around it.
- Do not import `fetchSettings` statically into `RunLaunchForm.tsx`, as explained in Context.
- Do not touch backend code; the API contract above is fixed.
- Numeric parsing: reject a boolean before treating a value as an integer, both for remembered counts and for anything you send.

## Done
Print a list of every file you changed and a one-paragraph summary of what you did. Then print a section headed exactly `Assumed, not verified`: every fact this change relies on that neither this brief nor the existing code settled, and that you did not confirm — the shape of an external service's request or response, an ambiguous requirement you resolved one way, a platform or library behaviour you expected, a value you chose. One item per line: what you assumed · why · what would confirm it. If there are none, print `Assumed, not verified: none`. Be specific: "edge cases" or "error handling" is not an item.
