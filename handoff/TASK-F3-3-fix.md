# TASK F3-3-fix — estimate must be cost-scoped, not spam non-cost edits, and tolerate invalid fields

Two Review blockers. RED-first: 3 new tests in RunLaunchForm.test.tsx are RED. Do NOT edit tests.

## Blocker 1 (Review A) — the estimate refetches on every keystroke
The estimate effect's dependency array includes the raw `values` object (new ref each keystroke) and
`params`, so it fires on ANY field edit, defeating the `estimateDepsKey` memo. Fix: the effect must
trigger ONLY when a cost-affecting input or `video_count` changes.

## Blocker 2 (Review B) — an invalid field makes the estimate post `params: {}`
The effect calls `collectParams(params, values)` which ABORTS on the first invalid field and returns
nothing, so while any field (e.g. a required empty `topic`) is invalid the estimate posts `{}` and the
endpoint returns the crude workflow-wide average instead of the estimate for the on-screen cost
settings. Fix: build the estimate's params from ONLY the `affects_cost` params' CURRENT values,
best-effort and tolerant of invalid non-cost fields — do NOT gate on full-form validity.

## Combined fix (frontend/src/components/RunLaunchForm.tsx)
- Add a helper that returns the cost-affecting params only: for each `param.affects_cost`, take its
  current value from `values`, parsing number-typed fields to a number when parseable (else omit or
  pass raw), ignoring every non-cost field. Call it e.g. `costParams(params, values)`.
- `estimateDepsKey` = a stable serialization of `costParams(...)` + `videoCount` (it already aims at
  this). Make the estimate effect's dependency array `[workflowId, estimateDepsKey]` ONLY (read
  `costParams` fresh inside the effect; add an eslint-disable-next-line exhaustive-deps if needed to
  keep lint clean). Remove `params`/`values`/`videoCount` from the dep array (they're folded into the key).
- Post `fetchEstimate(workflowId, costParams(params, values), videoCount)`.
- Failure handling: on a rejected estimate, KEEP the last good estimate (do not null it) and set the
  unavailable flag; render the empty "No estimate yet / no history" line ONLY when there is no estimate
  AND not unavailable (so the empty message and the error note never show together).

## Done when
- `npm --prefix frontend run test` passes (incl. the 3 new tests + all prior), lint + typecheck clean.
- End with an `Assumed, not verified` list (or `none`).
