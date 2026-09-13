# TASK G-3 — ranking UI in the "Your judgement" panel (§9, §11.1, `#p-video`)

## Goal (one sentence)
Add per-factor ranking (order the request's videos best-first) to the existing QualityPanel, folded
into the same Save, plus the mockup's `.rank*` styling and the verdict separator.

## Governing spec (verbatim — §9 / §11.1)
"… then ranks that request's videos against one another for each factor." "Rankings are relative and
within a single Generation Request. Learning value therefore scales with how many videos each request
produces — a request producing one video yields answers but no ranking, since there is nothing to
compare against." **No numeric ratings.**

## Backing API (already merged — do NOT change it)
The G-1 endpoint `POST /api/workflows/{id}/runs/{run}/quality` already accepts
`rankings: {factor_key: [video_index, ...]}` where each list is the request's video indices ordered
best-first, and validates each list is a permutation of ALL the request's video indices. Existing
rankings come back per video in `video_records[].quality.rankings` as `{factor_key: position}` (this
video's 1-based position for that factor).

## Current state (G-2, in this file — extend, don't rewrite)
`frontend/src/components/QualityPanel.tsx` renders per-video answer textareas + a tri-state verdict
and Saves `{ videos: collectSubmission(drafts) }`. `frontend/src/types.ts` has
`QualitySubmission = { videos: VideoQualityInput[] }`. The mockup's ranking classes
(`.rank/.rank-label/.rank-list/.rank-item/.rank-pos`) are NOT yet in `index.css`.

## What to implement

### 1. `frontend/src/types.ts`
Extend the submission type:
```ts
export type QualitySubmission = { videos: VideoQualityInput[]; rankings?: Record<string, number[]> };
```

### 2. `frontend/src/components/QualityPanel.tsx`
Ranking is per-factor and request-level (one ordering of all the run's videos per factor), shown
ONLY when there are at least two videos (a single-video request cannot rank — §11.1).

- Add ranking state `rankings: Record<string, number[]>` (factor key → video indices best-first),
  derived alongside `drafts` in the same guarded "sync on change" block. Initialise each factor's
  order from the recorded positions when present: for factor `k`, sort the video indices by
  `video.quality.rankings[k]` (ascending position = better); if a video has no recorded position for
  `k`, fall back to natural ascending index order. When nothing is recorded, use ascending index
  order. Parse `quality.rankings` defensively (untyped `Record<string, unknown>`), like the existing
  answer parsing — no `any`, no non-null `!`.
- Render a ranking section only when `drafts.length >= 2`, AFTER the per-video blocks and BEFORE the
  Save button. For each factor render a `.rank` block: a `.rank-label` reading
  `Rank the ${n} videos of this request` (n = video count) above the factor's question (reuse
  `.factor-q` for the question text), then a `.rank-list` of `.rank-item` rows in the factor's current
  order. Each `.rank-item` shows a `.rank-pos` (1-based position) and the video label
  (`Video NN` — reuse the existing `videoLabel`), plus two small buttons to reorder: "Move up" and
  "Move down" (disable "Move up" on the first row and "Move down" on the last). Give each reorder
  button an `aria-label` naming the video, factor, and direction (e.g. `Move Video 02 up for hook`) so
  the control is accessible. Do NOT implement drag-and-drop (keep it CSP-safe and accessible).
  Reordering swaps adjacent entries in that factor's `rankings[factor]` array (immutably, via
  setState).
- Include rankings in the submit: `submitQuality(workflowId, runId, { videos: collectSubmission(drafts),
  ...(drafts.length >= 2 ? { rankings } : {}) })`. (Only send `rankings` for multi-video requests; each
  array is already a full permutation because it started from all indices and reordering preserves the
  set.)

### 3. `frontend/src/index.css`
Port VERBATIM from `docs/SFVF_UI_Mockup.html` (the "quality" block): `.rank`, `.rank-label`,
`.rank-list`, `.rank-item`, `.rank-item:hover`, `.rank-pos`. Do NOT port `.rank-thumb` (we render no
thumbnails) or set `cursor: grab` — reordering is via buttons, so use the default cursor. Also add the
verdict separator the mockup shows (the design-auditor backlog item): give the `.verdict` row (or a
small wrapper) a `border-top: 1px solid var(--line-soft)` and top padding, so the verdict reads as its
own step. Only add rules / add the one border to `.verdict`; do not restyle other existing rules.

## Constraints / do-nots
- Touch ONLY: `frontend/src/components/QualityPanel.tsx`, `frontend/src/types.ts`,
  `frontend/src/index.css`. Do NOT change the backend, `app/api/quality.py`, any test, or other
  components. No new dependency. No drag-and-drop library.
- Do NOT commit `app/web/` build output (the supervisor restores `.gitkeep`).
- TypeScript strict: no `any`, no non-null `!` on untyped data. Keep `npm run build`, `npm run lint`,
  `npm run stylelint`, and `npx prettier --check` clean.

## Scope
- `frontend/src/components/QualityPanel.tsx`
- `frontend/src/types.ts`
- `frontend/src/index.css`

## Verify (from the worktree)
- `cd frontend && npm run build && npm run lint && npm run stylelint` → all clean.
- `npx prettier --check src/components/QualityPanel.tsx src/types.ts src/index.css` → clean.
- `./.venv/Scripts/python.exe -m pytest -q` (full) → still green (no backend change).
