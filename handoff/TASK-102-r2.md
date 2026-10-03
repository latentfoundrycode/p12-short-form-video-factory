# TASK-102 r2: launch-form review follow-ups

Satisfies: R-021, R-028, R-030 (refines TASK-102; read `handoff/TASK-102.md` for the full context — everything there still applies).

## Methodology (read first)

RED-first. The supervisor wrote the frozen contract `frontend/src/components/RunLaunchForm.r2.test.tsx` (5 tests, all failing now). Make them pass without editing any test file or `frontend/src/test/setup.ts`, and keep every other frontend test green (including `RunLaunchForm.chassis.test.tsx`, `RunLaunchForm.settingsrace.test.tsx`, `RunLaunchForm.test.tsx`, `RunLaunchForm.loading.test.tsx`).

## Scope

- frontend/src/components/RunLaunchForm.tsx
- frontend/src/index.css (only if a class is genuinely needed — prefer none)

## Requirements

1. **Dry run layout.** The Dry run control follows the pattern every other checkbox in the form uses: a `<label className="field-check">` holding the checkbox and its text, placed inside a `<div className="field">` (see the bool-param rendering in the same file). The label element must not carry the `field` class itself. Add a `.field-help` line under it: "Use fake assets; no spending." The text must not contain the words "manual", "budget", "video" or "voice" (other tests query those).
2. **Manual-input multiselect is remembered.** A `multiselect` param with `options === null` and `options_from === null` is entered as comma-separated text and submitted as an array of trimmed strings. When restored from `sfvf.launchForm.<workflowId>`, a remembered array of strings for such a param is shown as the items joined by `", "` (e.g. `["space","mars"]` → `"space, mars"`), so the field is pre-filled on the first render. A remembered value that is not an array of strings is ignored as before.
3. **Remembered decimals round-trip.** Restoring a remembered `number` param must produce text the point-only decimal grammar accepts. JavaScript's `String()` writes very small and very large magnitudes in scientific notation (`String(1e-7)` is `"1e-7"`, `String(1e21)` is `"1e+21"`), which the grammar rejects. Format the restored number in plain positional notation instead (no exponent), preserving its value exactly, so that a value the form accepted — e.g. `"0.0000001"` → stored `1e-7` → shown `"0.0000001"` — can be submitted again unchanged. A non-finite or non-number stored value is ignored as before.
4. **Remembered voice waits for the voice list.** Do not put a remembered voice into the submitted state until the loaded voice list confirms it. Until `fetchVoices` settles, the form's voice is the default `""`, so a submit before the list arrives sends `voice: ""`. When the list arrives and contains the remembered id, select it; when it does not, or the fetch fails, keep `""` (as today).

## Constraints

- Touch only the files in Scope. No new dependencies. Do not touch backend code or any test or test-setup file.
- Keep labels associated with their inputs; keep the checkbox native and keyboard-operable.
- Every localStorage access stays in try/catch; nothing logs with `console.error`.
- No hard line wraps inside Markdown paragraphs.
- Workspace boundary: read and write only inside this checkout. Note any tooling friction in `docs/BUILDER_NOTES.md`.

## Verify before handing back

```
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run typecheck
```

## Done

Print the files you changed, a one-paragraph summary, and an `## Assumed, not verified` section listing every fact you relied on without verifying (or `none`, only if truly none).
