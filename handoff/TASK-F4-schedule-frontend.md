# TASK F-4 — Schedule frontend tab (`v-schedule`, §8.6)

## Goal (one sentence)
Replace the `schedule` tab's placeholder with a real Schedule view that lists `schedules.json`
entries and lets the user add / edit / delete them, driving the F-3 CRUD API (`/api/schedules`).

## Governing spec (verbatim — Architecture §5.7 / the `/schedule` page)
> Reads `schedules.json`. When an entry is due it checks two conditions … if that workflow already
> has an active run, the slot is skipped; if the budget is insufficient, the slot is skipped …
> Missed slots are skipped rather than queued … Each entry carries the flag determining whether
> approval gates pause or pass automatically.

Owner decision (2026-09-12, `scheduler-paid-spend-per-schedule-opt-in`): a scheduled run is a **free
dry run** unless the entry opts into real spend. `allow_real_spend` is **off by default**, and the UI
must make "this will spend real money" **explicit** when it is turned on.

## The API this view drives (already merged, F-3 — do NOT change the backend)
Backed by `app/api/schedules.py`. Entry object = these nine fields exactly:
`id, workflow_id, days, time_of_day, video_count, concurrency, params, gates_auto, allow_real_spend`.
- `GET /api/schedules` → `{"schedules": [entry, ...]}` (empty when none).
- `POST /api/schedules` (body = the eight WRITABLE fields, NO `id`) → `201 <entry>`; invalid → `422`.
- `GET /api/schedules/{id}` → `200 <entry>` / `404`.
- `PUT /api/schedules/{id}` (body = the eight writable fields) → `200 <entry>` / `404` / `422`.
- `DELETE /api/schedules/{id}` → `204` / `404`.
Field rules (mirror server validation client-side so a valid form never 422s): `days` a NON-EMPTY
list of weekday indices 0..6 with **Monday=0 … Sunday=6**; `time_of_day` 24-hour zero-padded `"HH:MM"`;
`video_count` and `concurrency` integers ≥ 1; `params` a JSON object; `workflow_id` a safe segment
(use the workflow ids from `/api/workflows`).

## Frontend conventions (match these exactly — read the files first)
- `frontend/src/components/StatisticsView.tsx` — the canonical fetch-view: `status` =
  `"loading" | "ready" | "error"`, a `cancelled` guard in the effect, a Retry that bumps a
  `reloadKey`. Copy this shape.
- `frontend/src/components/RunLaunchForm.tsx` — the canonical form: controlled inputs, a
  `parseParamsObject` JSON validator, client-side checks before submit, `formError`, a `submitting`
  flag. Reuse the same params-JSON handling.
- `frontend/src/components/RunsListView.tsx` — back/list navigation idiom and `messageOf`.
- `frontend/src/api.ts` / `frontend/src/types.ts` — extend, don't restructure.

## What to implement

### 1. `frontend/src/types.ts`
Add (place near the other list/body types):
```ts
export type ScheduleEntry = {
  id: string;
  workflow_id: string;
  days: number[];
  time_of_day: string;
  video_count: number;
  concurrency: number;
  params: Record<string, unknown>;
  gates_auto: boolean;
  allow_real_spend: boolean;
};
export type ScheduleList = { schedules: ScheduleEntry[] };
// The create/update body: the writable fields only (the server generates and owns `id`).
export type ScheduleWriteBody = Omit<ScheduleEntry, "id">;
```

### 2. `frontend/src/api.ts`
Add four functions, following the existing error idiom (throw an `Error` with a readable message on
a non-OK response; validate the JSON shape like `fetchRuns`/`fetchStatistics` do):
- `fetchSchedules(): Promise<ScheduleEntry[]>` — GET; validate `Array.isArray(data.schedules)`.
- `createSchedule(body: ScheduleWriteBody): Promise<ScheduleEntry>` — POST; on `201` return the
  entry; on `422` throw `new Error("The server rejected these schedule values.")`; else throw with
  the status.
- `updateSchedule(id: string, body: ScheduleWriteBody): Promise<ScheduleEntry>` — PUT
  `/api/schedules/{encodeURIComponent(id)}`; `200` → entry; `404` → throw "That schedule no longer
  exists."; `422` → same reject message; else status.
- `deleteSchedule(id: string): Promise<void>` — DELETE; `204` → resolve; `404` → throw "That
  schedule no longer exists."; else status.

### 3. `frontend/src/components/ScheduleView.tsx` (new)
A view (`<section className="view on">`) that fetches BOTH schedules and workflows (it needs
`/api/workflows` to resolve a `workflow_id` to a display name and to populate the Add form's workflow
picker — use the existing `fetchWorkflows`). Follow `StatisticsView`'s loading/ready/error+Retry
shape. Structure:

- **Page head:** title "Schedule"; note text exactly: "A slot is skipped if the workflow is still
  running or the budget is short. Missed slots are not queued." (from the mockup); an "Add entry"
  primary button (`btn btn-primary btn-sm`) that opens the form in create mode.
- **List** (`panel` → `list` → one `li` per entry), each `li`:
  - `li-main`: `li-title` = the workflow's name (fall back to `workflow_id` when unknown/unnamed);
    `li-sub` (line 1) = `"{video_count} videos"` (singular "1 video"), append `", {concurrency} at a
    time"` only when `concurrency > 1`, then the spend status: real spend → `"· spends real money"`,
    otherwise → `"· dry run (free)"`; `li-sub` (line 2) = `gates_auto ? "Gates pass automatically" :
    "Pauses at gates"`.
  - `days`: seven `day` spans labelled `M T W T F S S`, each with `on` when its index (0=Mon … 6=Sun)
    is in `entry.days`.
  - `time`: `entry.time_of_day`.
  - An "Edit" button (`btn btn-sm btn-ghost`) opening the form in edit mode for that entry.
  - Empty state when there are no entries: a `panel`/`page-note` "No schedules yet."
- **Add/Edit form** (render inline in a `panel`, replacing or above the list while open — do NOT
  build a modal-overlay system; keep it in-page like `RunLaunchForm`). Controlled fields:
  - Workflow: a `select.sel` of the VALID workflows (`valid === true`); in edit mode it is preset and
    may stay editable. Show the workflow name (fall back to id).
  - Days: seven toggle buttons reusing the `day`/`day on` styling (clicking flips membership). At
    least one day required.
  - Time: an `<input type="time">` (or a text input constrained to `HH:MM`) bound to `time_of_day`.
  - Video count, Concurrency: `field-input` number inputs (min 1, step 1), like `RunLaunchForm`.
  - Gates: a `switch`/`tog` toggle (see CSS below) labelled so ON = "Gates pass automatically", OFF =
    "Pauses at gates", bound to `gates_auto`.
  - Real spend: a `switch`/`tog` toggle bound to `allow_real_spend`, OFF by default. When ON, show an
    explicit warning block (reuse the mockup's `blocker` style — red-bordered) reading "This schedule
    will spend real money on each run." When OFF, no warning; optionally a faint "Runs as a free dry
    run." note.
  - Params: a JSON-object textarea (`field-textarea`) reusing `RunLaunchForm`'s `parseParamsObject`.
  - Actions: "Save" (`btn btn-primary btn-sm`, calls `createSchedule` or `updateSchedule`), "Cancel"
    (`btn btn-ghost btn-sm`), and in edit mode a "Delete" (`btn btn-sm`) guarded by a
    `window.confirm(...)` before calling `deleteSchedule`. A `submitting` flag disables the controls;
    a `form-error` shows validation/API messages.
  - Client-side validation BEFORE submit (mirror the server): ≥ 1 day, `time_of_day` matches
    `^([01]\d|2[0-3]):[0-5]\d$`, integer counts ≥ 1, params a JSON object, a workflow selected.
  - After a successful create/update/delete: close the form and refetch the list (bump a reload key).

### 4. `frontend/src/App.tsx`
Route `tab === "schedule"` to `<ScheduleView />` (import it) instead of falling through to
`PlaceholderView`. Leave every other branch unchanged.

### 5. `frontend/src/index.css`
The classes `list, li, li-main, li-title, li-sub, days, day, time, switch, tog` are used by the
mockup but NOT yet in the app CSS. Port them VERBATIM from `docs/SFVF_UI_Mockup.html` (the block under
"SCHEDULE / LEARNING / STATS / SETTINGS" plus `.switch`/`.tog`). Add the `blocker` style (red-bordered
warning row) from the mockup too, for the real-spend warning. Do not restyle existing classes; only
add. Keep `stylelint` clean (match the file's ordering/format conventions).

## Deliberate deviation to record (do NOT try to "fix" toward the mockup)
The mockup's per-entry sub-line shows a budget ("budget €2.00 and 150 cr"). The F-1 `ScheduleEntry`
model has **no per-entry budget field** — the global budget applies, per the frozen data layer. So
this view shows the **real-spend / dry-run status** (and video/concurrency) in that sub-line instead
of a budget. This is a faithful mapping to the actual API, not an omission. State this deviation in
your summary so the design reviewer does not flag the missing budget line.

## Constraints / do-nots
- Touch ONLY: `frontend/src/types.ts`, `frontend/src/api.ts`,
  `frontend/src/components/ScheduleView.tsx` (new), `frontend/src/App.tsx`, `frontend/src/index.css`.
- Do NOT change any backend file, any test, the mockup, or other components. Do NOT add a dependency.
- Do NOT commit build output: `npm run build` writes into `app/web/` — leave those artifacts
  uncommitted (the supervisor restores `app/web/.gitkeep` at commit time).
- TypeScript strict: no `any`, no non-null `!` on untyped data — validate shapes like the existing
  api helpers. Keep `npm run lint`, `npm run stylelint`, and `npm run build` clean.

## Scope
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/components/ScheduleView.tsx`
- `frontend/src/App.tsx`
- `frontend/src/index.css`

## Verify (from the worktree)
- `cd frontend && npm run build` → tsc + vite build succeed with no type errors.
- `cd frontend && npm run lint` → eslint clean.
- `cd frontend && npm run stylelint` → clean.
- `cd frontend && npm run format:check` → clean (run `npm run format` if needed).
