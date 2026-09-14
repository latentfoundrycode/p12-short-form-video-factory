# TASK G-4 — Learning tab (read-only list of label counts, §8.5 `v-learning`)

## Goal (one sentence)
Add `GET /api/learning` (per-workflow quality-label + rules/skills counts) and replace the Learning
tab placeholder with a read-only list of workflows and their accumulated labels — the informational
half of `v-learning`. Starting a learning run is the PAID optimiser (G-5) and is NOT built here.

## Governing spec (verbatim — §8.5)
"Lists every workflow together with how many quality labels have accumulated since its last learning
run. No minimum is imposed — the count is shown so the user can decide when there is enough to be
worth acting on."

## Frozen contract (already committed — do NOT edit)
`tests/api/test_learning_api.py` pins `GET /api/learning`.

## What to implement

### 1. `app/api/learning.py` (new)
`router = APIRouter(prefix="/api")`. `GET /api/learning` → `LearningListOut` with a
`workflows: list[LearningRowOut]`, one row per registered workflow in the registry's snapshot order
(folder-name order — same source as `app/api/workflows.py`'s `_holder(request).snapshot`). Each
`LearningRowOut` has: `workflow_id: str`, `name: str | None`, `label_count: int`, `rules_count: int`,
`skills_count: int`, `last_learned: str | None`.
- `workflow_id` = `entry.folder_name`; `name` = `entry.manifest.workflow.name` (None if manifest None).
- `label_count`: scan the workflow's runs and count videos whose recorded quality has ≥1 worded
  answer. Mirror the run-scan in `app/core/statistics.py` (`_iter_run_dirs` / iterate
  `runs_dir / workflow_id`'s run dirs → each `video.json`): for each run dir with a `request.json`,
  for each child dir containing `video.json`, `read_video(child)` and count it when
  `record.quality` is a dict whose `answers` is a non-empty dict. Missing runs dir → 0. Use
  `_runs_dir(request)` (as `app/api/runs.py` does) for the runs root.
- `rules_count` / `skills_count`: number of `*.md` files directly in `entry.path / "rules"` and
  `entry.path / "skills"` (0 if the dir is absent). Top-level `*.md` only (not recursive).
- `last_learned`: always `None` for now (no learning run records one until G-5).
Add response models; register the router in `app/main.py` (`include_router`) alongside the others.

### 2. `frontend/src/types.ts`
```ts
export type LearningRow = {
  workflow_id: string;
  name: string | null;
  label_count: number;
  rules_count: number;
  skills_count: number;
  last_learned: string | null;
};
export type LearningList = { workflows: LearningRow[] };
```

### 3. `frontend/src/api.ts`
`export async function fetchLearning(): Promise<LearningRow[]>` — `GET /api/learning`; validate
`Array.isArray(data.workflows)`; throw a readable Error on non-OK (follow `fetchStatistics`/`fetchRuns`).

### 4. `frontend/src/components/LearningView.tsx` (new)
Follow `StatisticsView`'s fetch-view shape (`status` = loading | ready | error, `cancelled` guard,
Retry via a reload key). Page head: title "Learning", note exactly "Proposes edits to a workflow's
own rules and skills from your answers and rankings. Global instructions are never touched." Then a
`panel` with `panel-head` eyebrow "Workflows" and a `list` of `.lrn` rows, one per workflow:
- `.lrn-count` = the number with a `<small>labels</small>` under it (e.g. `12<small>labels</small>`).
- `.li-main` with `.li-title` = `name || workflow_id`, and a `.li-sub` line = `${rules_count} rules,
  ${skills_count} skills`, prefixed with `Last learned ${last_learned} · ` ONLY when `last_learned`
  is non-null (it is always null for now, so the sub-line shows just the counts).
- Do NOT render a "Start learning" button or any running/done state — those arrive with the optimiser
  (G-5). Empty state: a `page-note` "No workflows yet." when the list is empty.

### 5. `frontend/src/App.tsx`
Route `tab === "learning"` to `<LearningView />` (import it), placed beside the `statistics` branch.

### 6. `frontend/src/components/PlaceholderView.tsx`
`learning` is now handled, and `schedule` already routes to `ScheduleView`. Narrow `PlaceholderTab` to
just the still-placeholdered tab: `type PlaceholderTab = Extract<TabId, "settings">;` and reduce the
`LINES`/`TITLES` records to the `settings` entry only. (App only ever passes `settings` to it now.)

### 7. `frontend/src/index.css`
Port VERBATIM from `docs/SFVF_UI_Mockup.html` (lines 463-471): `.lrn`, `.lrn:last-child`,
`.lrn-count`, `.lrn-count small`. Do NOT port `.lrn.s-run` / `.lrn.s-done` (those states arrive with
G-5). `.list`/`.li-main`/`.li-title`/`.li-sub` already exist (from F-4). Only add; do not restyle.

## Constraints / do-nots
- Touch ONLY the files listed under ## Scope. Do NOT edit any test, start any learning run, or build a
  Start button / review interface (G-5+). No new dependency.
- Do NOT commit `app/web/` build output (the supervisor restores `.gitkeep`).
- Backend `ruff`/`mypy sdk app` clean; frontend `npm run build`/`lint`/`stylelint`/`prettier` clean.

## Scope
- `app/api/learning.py`
- `app/main.py`
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/components/LearningView.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/PlaceholderView.tsx`
- `frontend/src/index.css`

## Verify (from the worktree)
- `./.venv/Scripts/python.exe -m pytest tests/api/test_learning_api.py -q` → all pass.
- `./.venv/Scripts/python.exe -m pytest -q` (full) → green; `-m ruff check .`, `-m mypy sdk app` clean.
- `cd frontend && npm run build && npm run lint && npm run stylelint && npx prettier --check src` → clean.
