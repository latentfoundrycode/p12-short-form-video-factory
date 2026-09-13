# TASK G-2 — quality-capture UI: answers + verdict (§9, §11.1, `#p-video` "Your judgement")

## Goal (one sentence)
Let the user record, on a finished run, a free-text answer to each declared quality factor per video
plus an accept/reject verdict, saved via the G-1 API — the "Your judgement" panel, minus ranking
(ranking is G-3).

## Governing spec (verbatim — §9)
"After a Generation Request finishes, the user writes a free-text answer to each factor for every
video … Accept or reject is recorded separately. **There are no numeric ratings.**"

## Frozen contract (already committed — do NOT edit)
`tests/api/test_workflows.py` — pins that `WorkflowOut` exposes `quality_factors` (a list of
`{key, question}`), `[]` for a workflow that declares none or is invalid.

## Backing API (merged in G-1 — do NOT change it)
`POST /api/workflows/{id}/runs/{run}/quality` with body
`{"videos": [{"index", "answers": {factor_key: text}, "accepted": bool}], "rankings": {}}`.
For G-2 send `answers` + `accepted` only (omit `rankings`, or send `{}`). Existing answers/verdict for
a run are already returned by `GET /api/workflows/{id}/runs/{run}` in `video_records[].quality`
(`{"answers"?, "accepted"?, "rankings"?}`).

## What to implement

### 1. `app/api/workflows.py` — expose the factors
Add a `QualityFactorOut(BaseModel)` with `key: str` and `question: str`, and a
`quality_factors: list[QualityFactorOut]` field on `WorkflowOut`. In `_serialize`, populate it:
`[]` when `manifest is None`, else `[QualityFactorOut(key=f.key, question=f.question) for f in
manifest.quality_factors]`. Change nothing else.

### 2. `frontend/src/types.ts`
```ts
export type QualityFactor = { key: string; question: string };
```
Add `quality_factors: QualityFactor[];` to the `Workflow` type. Add the submission types:
```ts
export type VideoQualityInput = { index: number; answers: Record<string, string>; accepted: boolean | null };
export type QualitySubmission = { videos: VideoQualityInput[] };
```

### 3. `frontend/src/api.ts`
`export async function submitQuality(workflowId: string, runId: string, body: QualitySubmission): Promise<void>`
— `POST` to `/api/workflows/{encodeURIComponent(workflowId)}/runs/{encodeURIComponent(runId)}/quality`
with `Content-Type: application/json`; on non-2xx throw an `Error` with a readable message (422 →
"The server rejected these answers."; else the status). Follow the existing `startRun`/`fetchRuns`
error idiom.

### 4. `frontend/src/components/QualityPanel.tsx` (new)
Props: `{ workflowId: string; runId: string; videos: VideoRecord[]; onSaved: () => void }` (the run's
`video_records`, in order). On mount, fetch the workflow list (`fetchWorkflows`) and find the entry
whose `id === workflowId` to read its `quality_factors`. If it has none, render nothing (the panel is
only meaningful when factors are declared).

Otherwise render a `panel` titled (eyebrow) "Your judgement" with a `rq-meta` note "words, no scores".
For EACH video (ascending index) render a labelled sub-block: the video label ("Video NN"), then for
each factor its `factor-q` question + a `ta` textarea (controlled; pre-filled from
`videos[i].quality?.answers?.[key]`), then a `verdict` row with two buttons — "Accepted" and "Reject"
— reflecting/toggling that video's `accepted` (pre-filled from `videos[i].quality?.accepted`; tri-state
allowed: null = neither chosen). One "Save judgement" button at the foot POSTs a `QualitySubmission`
with every video that has at least one non-empty answer or a non-null verdict, then calls `onSaved()`.
Use `submitting`/`formError` like `RunLaunchForm`. Parse the untyped `quality` defensively (it is
`Record<string, unknown> | null`), mirroring how `RunRecordView` already reads `self_review`.

### 5. `frontend/src/components/RunRecordView.tsx`
Render `<QualityPanel workflowId={...} runId={...} videos={video_records} onSaved={reload}/>` within
the terminal-run record view (near the per-video panels). `onSaved` should re-trigger the view's
existing data load so saved answers/verdict are reflected. Do not disturb the existing panels.

### 6. `frontend/src/index.css`
Port VERBATIM from `docs/SFVF_UI_Mockup.html` (the "quality" block): `.factor`, `.factor-q`, `.ta`,
`.ta::placeholder`, `.verdict`, and `.rq-meta`. Do NOT port the `.rank*` classes (that is G-3). Only
add; do not restyle existing rules.

## Constraints / do-nots
- Touch ONLY: `app/api/workflows.py`, `frontend/src/types.ts`, `frontend/src/api.ts`,
  `frontend/src/components/QualityPanel.tsx` (new), `frontend/src/components/RunRecordView.tsx`,
  `frontend/src/index.css`. Do NOT edit any test or the G-1 endpoint. No ranking UI (G-3). No new dep.
- Do NOT commit `app/web/` build output (the supervisor restores `.gitkeep`).
- TypeScript strict: no `any`, no non-null `!` on untyped data. Keep `npm run build`, `npm run lint`,
  `npm run stylelint` clean, and `mypy sdk app` / `ruff` clean for the backend change.

## Scope
- `app/api/workflows.py`
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/components/QualityPanel.tsx`
- `frontend/src/components/RunRecordView.tsx`
- `frontend/src/index.css`

## Verify (from the worktree)
- `./.venv/Scripts/python.exe -m pytest tests/api/test_workflows.py -q` → all pass.
- `./.venv/Scripts/python.exe -m pytest -q` (full) → green; `-m ruff check .`, `-m mypy sdk app` clean.
- `cd frontend && npm run build && npm run lint && npm run stylelint` → all clean.
