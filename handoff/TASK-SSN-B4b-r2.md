# TASK-SSN-B4b-r2 — Use the idiomatic static import for fetchVoices (craft cleanup)

Two reviewers (diff-reviewer + design-auditor) converged on one line in `frontend/src/components/RunLaunchForm.tsx`: the on-mount voice-fetch effect uses a dynamic `await import("../api")` plus a runtime `if (!("fetchVoices" in mod))` existence check, instead of the idiomatic static import the sibling model-select effect uses. Make it consistent. Behaviour must not change; the existing frozen tests must stay green (do NOT edit any test).

## Fix (RunLaunchForm.tsx only)

1. Add `fetchVoices` to the static top-level import from `../api` (the line that already imports `fetchProviderOptions, startRun`), and in the on-mount effect call `fetchVoices()` directly (like the `fetchProviderOptions` effect), removing the dynamic `import("../api")` and the `"fetchVoices" in mod` feature-check. Keep the exact behaviour: fetch on mount, populate the voice options, and on failure keep just the "Default voice" option with no console.error.
2. Drop the redundant `aria-label="Voice"` on the Voice `<select>` -- the wrapping `<label className="field">` with the "Voice" `field-label` already supplies the accessible name (matching the sibling selects and what the frozen test asserts via role/name).

Leave everything else as-is.

## Scope

- frontend/src/components/RunLaunchForm.tsx

Do NOT modify: any test, other files, dependencies. Do NOT run `npm run build`.

## Done when

- `npm --prefix frontend run test -- --run` passes (all RunLaunchForm cases incl. the voice picker), `npm --prefix frontend run lint` and `npm --prefix frontend run typecheck` clean.
- Print the one-line change summary.
