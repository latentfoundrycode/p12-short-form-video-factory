# TASK — in-app rules/skills editor: frontend (expand → list → view → edit → save)

## Goal (one sentence)
In the Learning tab, let the user expand a workflow to see its rule/skill files, click one to view it
in the right panel, and Edit → Save it (the button toggles Edit↔Save), persisting through the backend
save endpoint that archives + version-bumps.

## Owner's spec (verbatim intent)
"When I click on a workflow that is listed in the Learning tab it should expand and show me a list of
all the rules and skill markdown files. When clicking on them, the panel that displays them should open
on the right, just like when reviewing a new rule/skill. Then there should be an edit button, which
makes me able to edit the file. Then I can click on save (the edit button transformed to saying 'Save'
after clicking 'Edit' once) to save it and no longer have an input field in that state."

## Backend already merged (#95) — use these endpoints
- `GET /api/learning/{workflow_id}/instructions` -> `{"instructions": [{"path": "rules/tone.md",
  "content": "..."}]}` — every `rules/*.md` then `skills/*.md`, rules before skills.
- `PUT /api/learning/{workflow_id}/instructions` with `{"path": "rules/tone.md", "content": "..."}` ->
  `{"path": "rules/tone.md", "version": <int>}` — saves one existing file (archives prior + bumps
  version). 400 on a bad path, 404 if the file is missing.

## What to change

### 1. `frontend/src/types.ts`
Add:
```ts
export type InstructionFile = { path: string; content: string };
export type InstructionsList = { instructions: InstructionFile[] };
export type SaveInstructionResult = { path: string; version: number };
```

### 2. `frontend/src/api.ts`
Add two functions matching the existing style (throw on non-ok, validate shape):
```ts
export async function fetchInstructions(id: string): Promise<InstructionFile[]> {
  const response = await fetch(`/api/learning/${encodeURIComponent(id)}/instructions`);
  if (!response.ok) throw new Error(`Could not load instruction files (${response.status})`);
  const data = (await response.json()) as InstructionsList;
  if (!Array.isArray(data.instructions))
    throw new Error("Unexpected response while trying to load instruction files");
  return data.instructions;
}

export async function saveInstruction(
  id: string, path: string, content: string,
): Promise<number> {
  const response = await fetch(`/api/learning/${encodeURIComponent(id)}/instructions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  if (!response.ok) throw new Error(`Could not save instruction file (${response.status})`);
  const data = (await response.json()) as SaveInstructionResult;
  if (typeof data.version !== "number")
    throw new Error("Unexpected response while trying to save instruction file");
  return data.version;
}
```
Add `InstructionFile`, `InstructionsList`, `SaveInstructionResult` to the `import type { ... }` block.

### 3. `frontend/src/components/LearningView.tsx` — the interaction
Keep everything that exists (the learning-run / Start learning / Review / Accept-Reject proposal flow
is untouched). ADD an expand-and-edit surface. Suggested state:

- `expandedId: string | null` — the workflow whose files are shown. Clicking a workflow row toggles it.
- `filesByWorkflow: Record<string, { status: "idle" | "loading" | "ready" | "error"; files:
  InstructionFile[]; error: string | null }>` — lazily fetched via `fetchInstructions` when a row is
  first expanded.
- `selectedFile: { workflowId: string; path: string } | null` — which file the right panel shows.
- `editing: boolean`, `draft: string`, `saving: boolean`, `saveError: string | null`,
  `savedVersion: number | null`.

Behaviour:
- **Expand:** clicking a workflow's main area toggles `expandedId`. On expand, if that workflow's entry
  is not yet `ready`, set it `loading` and call `fetchInstructions(id)` → store `ready` + files (or
  `error`). Do NOT break the existing row buttons (Start learning / Review / Dismiss / Retry) — the
  expand toggle must not fire when those buttons are clicked (stop propagation on the buttons, or make
  the expand affordance a distinct clickable element such as the `.li-main` area / a caret button).
- **File list (under an expanded row):** render each `InstructionFile` as a clickable item showing its
  `path` (e.g. `rules/tone.md`). Empty state: "No rule or skill files yet." A `loading`/`error` note as
  appropriate. Rules already precede skills (API order) — preserve it.
- **Select a file:** clicking a file sets `selectedFile = {workflowId, path}`, leaves `editing=false`,
  clears `saveError`/`savedVersion`, and clears any proposal-review selection (`setSelectedWorkflowId(
  null)`) so the two right-panel modes never both show. Symmetrically, choosing Review/Start for
  proposals clears `selectedFile`.
- **Right panel — file mode** (when `selectedFile` is set and no proposals are being reviewed): a
  `.panel` with a `.panel-head` (eyebrow = the file path) and a body. In VIEW mode show the file content
  read-only, reusing the same look as the proposal panel (`.diff` / `.diff-head` / `.diff-body` with the
  content split into `.dl` lines), and an **Edit** button. In EDIT mode replace the read-only body with
  a `<textarea className="field-input field-textarea">` bound to `draft` (min a dozen rows), and the
  button now reads **Save**. `saveError` shows via `.form-error`; `savedVersion` shows a small confirming
  note (e.g. "Saved · version N").
- **Edit click:** `editing = true`, `draft = <current file content>`, button label → "Save".
- **Save click:** `saving = true`; `await saveInstruction(workflowId, path, draft)`. On success:
  `editing=false`, `savedVersion=<returned>`, update that file's `content` in `filesByWorkflow` to the
  saved `draft` (so re-opening shows the saved text), button label back to "Edit". Re-fetch that
  workflow's instructions in the background so the stored content reflects the server's version bump
  (optional but preferred). On failure: keep `editing=true`, set `saveError`, `saving=false`.
  Disable the Save button while `saving`.

Use only existing CSS classes (`.two`, `.panel`, `.panel-head`, `.panel-body`, `.list`, `.lrn`,
`.li-main`, `.li-title`, `.li-sub`, `.diff`, `.diff-head`, `.diff-body`, `.dl`, `.dl-mark`, `.btn`,
`.btn-sm`, `.btn-primary`, `.btn-ghost`, `.eyebrow`, `.pill`, `.field`, `.field-input`,
`.field-textarea`, `.form-error`, `.page-note`, `.card-foot`, `.review-actions`). If you need a small
amount of new CSS (e.g. an expanded-file list indent or a caret), add it to `frontend/src/index.css`
using existing CSS variables (`--surface-2`, `--line`, `--text`, `--text-faint`, `--r`, `--font-mono`)
and match the surrounding style; keep it minimal.

## Constraints / do-nots
- Touch ONLY `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/components/LearningView.tsx`,
  and (if strictly needed) `frontend/src/index.css`.
- Do NOT commit built assets. Never write into `app/web/` and never touch `app/web/.gitkeep`.
- Do NOT change the existing learning-run/proposal flow behaviour.
- Keep `npm run lint` and `npm run typecheck` clean; no `any`, no non-null-assertion hacks; match the
  existing React 19 + hooks idiom (the file uses functional updates like `setRuns((current) => ...)`).

## Scope
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/components/LearningView.tsx`
- `frontend/src/index.css` (only if a little new style is unavoidable)

## Verify (from the worktree)
- `cd frontend && npm run lint` → clean.
- `cd frontend && npm run typecheck` → clean.
- `cd frontend && npm run build` → succeeds (do NOT commit the `app/web/` output it produces).
- `cd frontend && npm run format:check` and `npm run stylelint` → clean (hygiene; fix if they flag your
  new lines).
