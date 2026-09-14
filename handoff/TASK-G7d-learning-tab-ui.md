# TASK G-7d — Learning tab: Start, run states, and the review interface (§5.11, Frontend §6)

## Goal (one sentence)
Turn the read-only Learning tab into the working run/review flow: start a learning run per workflow,
watch its state, and review the staged proposals with Accept-all / Reject — wired to the G-7c
endpoints. No new dependencies; reuse the design system.

## Governing spec
- Architecture §5.11: "run the SkillOpt-derived optimiser to propose bounded edits. … Proposals are
  written to a staging area and never applied directly. The live files are untouched until the user
  accepts."
- Frontend §6 route `/learning`: "The Learning tab and the review interface."
- Design reference: `docs/SFVF_UI_Mockup.html`, the `#v-learning` section (two-column `.two`
  layout: left = Workflows list with per-row states; right = the "Proposed · <name>" review panel).

## Endpoints (already merged, G-7c) — all under `/api`
- `POST /learning/{id}/run` → `{ "staged": [{ "path": string, "content": string }, ...] }` (502 on
  failure). `GET /learning/{id}/staged` → same shape. `POST /learning/{id}/accept` → `{ "applied":
  [string, ...] }`. `POST /learning/{id}/reject` → `{ "ok": true }`. `GET /learning` → the existing
  list (unchanged).

## What to implement (FOUR files)

### 1) `frontend/src/types.ts` — add
```ts
export type StagedProposal = { path: string; content: string };
export type StagedList = { staged: StagedProposal[] };
export type AcceptResult = { applied: string[] };
```

### 2) `frontend/src/api.ts` — add four functions (mirror the existing fetch/error style)
- `runLearning(id: string): Promise<StagedProposal[]>` → `POST /api/learning/{id}/run` (encodeURIComponent);
  on `!ok` throw `Error("Could not start learning (" + status + ")")`; parse `StagedList`, return
  `data.staged` (guard it is an array).
- `fetchStaged(id: string): Promise<StagedProposal[]>` → `GET /api/learning/{id}/staged`; same guards.
- `acceptLearning(id: string): Promise<string[]>` → `POST /api/learning/{id}/accept`; parse
  `AcceptResult`, return `data.applied` (guard array).
- `rejectLearning(id: string): Promise<void>` → `POST /api/learning/{id}/reject`; throw on `!ok`.

### 3) `frontend/src/components/LearningView.tsx` — the run/review flow
Keep the existing page head and the initial `GET /learning` load (loading/error/ready). Replace the
single "Workflows" panel with a two-column `.two` layout:

**Left panel — "Workflows"** (`.panel` > `.panel-head` eyebrow "Workflows" > `.list`). Each row is a
`.lrn` (reuse the existing `.lrn-count`, `.li-main`, `.li-title`, `.li-sub`). Track a per-workflow
run-state in component state, one of: `"idle" | "running" | "ready" | "error"`.
- `idle`: sub-line = the existing counts/last-learned detail; action = a `btn btn-sm` **"Start
  learning"** button, `disabled` when `label_count === 0`. Click → set that row to `running`, then
  `runLearning(id)`.
- `running`: add class `s-run` to the `.lrn` (→ `.lrn.s-run`); sub-line "Reading {label_count}
  labels…" (this line only, styled via the class, not an inline color); action = `<span class="pill
  run">Running</span>` (no button). On resolve → store the staged proposals for that workflow, set
  state `ready`, and select it into the right panel. On reject → state `error`.
- `ready`: add class `s-done`; sub-line "{n} edits proposed, awaiting your review" where n = staged
  length (if n === 0, "No changes proposed" and no Review button — treat as back-to-idle after a
  moment is fine, but at minimum do not offer Review for an empty set); action = a `btn btn-primary
  btn-sm` **"Review"** button that selects this workflow into the right panel.
- `error`: sub-line = the error message; action = a `btn btn-sm` **"Retry"** that returns the row to
  `idle` (the user can Start again).
Only one run in flight per row; the button is absent while `running`.

**Right panel — the review interface.** Shown only when a workflow is selected AND has staged
proposals. `.panel` > `.panel-head` with `<span class="eyebrow">Proposed · {name}</span>` and a
`<span class="pill done">{n} edits</span>`. Body (`.panel-body`): for each proposal, a `.diff` block:
- `.diff-head` with `<span>{path}</span>` and `<span>proposed</span>`.
- `.diff-body` containing the proposed file content split into lines, each a `<div class="dl"><span
  class="dl-mark"> </span><span>{line}</span></div>` (context lines only — see the scope note on the
  line-level diff). Preserve empty lines.
Then an actions row (`display:flex; gap:8px` via a small reused wrapper, e.g. `card-foot` or an inline
style matching the mockup) with:
- `btn btn-primary btn-sm` **"Accept all {n}"** → `acceptLearning(id)` → on success clear the right
  panel, reset the row to `idle`, and re-run the initial `GET /learning` load so counts refresh.
- `btn btn-sm btn-ghost` **"Reject"** → `rejectLearning(id)` → clear the panel, reset the row to
  `idle`.
Guard against double-submit (disable the buttons while an accept/reject is in flight). Surface an
accept/reject failure inline (a `page-note` with the error) without losing the staged view.

Accessibility: real `<button type="button">` elements (never divs); the disabled Start uses the
`disabled` attribute; buttons have discernible text.

### 4) `frontend/src/index.css` — add ONLY the missing rules (copy from the mockup, app-formatted)
The app already defines all tokens and `.lrn`, `.lrn-count`, `.pill(.run/.done)`, `.btn(-primary/
-ghost)`, `.panel-body`. Add, matching the app's existing multi-line property style and stylelint
config (this is the ONLY place new CSS is allowed):
- `.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }` plus
  `@media (max-width: 960px) { .two { grid-template-columns: 1fr; } }`.
- `.lrn.s-run { border-left: 2px solid var(--amber); background: var(--amber-bg); }`
- `.lrn.s-done { border-left: 2px solid var(--green); background: var(--green-bg); }`
- `.diff`, `.diff-head`, `.diff-body`, `.dl`, `.dl-mark` exactly as in the mockup lines 473-486 (you
  may omit `.dl.add`/`.dl.del` since this increment renders context lines only — but including them
  verbatim is fine and harmless). Use the existing tokens (`--line`, `--r`, `--surface-2`,
  `--font-mono`, `--text-dim`, `--text-faint`).
Do not restyle existing selectors. Keep stylelint-config-standard happy (lowercase hex,
`rgb(r g b / N%)` form already used by the tokens, no duplicate selectors).

## Scope deviations from the mockup (intentional — for the design reviewer)
- **No line-level add/del diff and no "Why" rationale.** The `/staged` payload is the PROPOSED file
  content only; there is no current-vs-proposed diff and `ProposedEdit` carries no rationale. We reuse
  the `.diff` block to preview the proposed content as context lines. A true add/del diff (needs the
  current file content) and the "Why" note (needs the optimiser to return a reason) are deferred.
- **No "Accept selected".** The backend applies the WHOLE staged set (`accept_learning`) or discards
  it (`reject_learning`); there is no per-file selection. Offer only "Accept all {n}" and "Reject".
- **Per-row persistent "proposals-ready" badge / real `last_learned` are not driven on load.** The
  `GET /learning` list does not report staged-existence or a last-learned marker yet (tracked as the
  separate "since the last learning run" checkpoint increment). State here is driven by in-session
  actions; on reload rows start `idle`. Keep rendering `last_learned` if the API ever returns it.

## Constraints / do-nots
- Touch ONLY: `frontend/src/types.ts`, `frontend/src/api.ts`,
  `frontend/src/components/LearningView.tsx`, `frontend/src/index.css`. Do NOT edit `app/web/` (build
  output), other components, or any Python.
- No new npm dependency. React 19 + the existing patterns only.
- After building, the vite build wipes `app/web/`; do NOT commit any change under `app/web/` (it is
  gitignored except `.gitkeep` — leave `.gitkeep` in place; do not stage app/web).

## Scope
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/components/LearningView.tsx`
- `frontend/src/index.css`

## Verify (from `frontend/`, using the junctioned node_modules)
- `npm run typecheck` → clean.
- `npm run lint` → clean.
- `npm run format:check` → clean (run `npm run format` if needed, but only over the four files).
- `npm run stylelint` → clean.
- `npm run build` → succeeds (tsc -b && vite build). Do not commit the emitted `app/web/` output.
