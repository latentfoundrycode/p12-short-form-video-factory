# TASK — friendly param-driven launcher (replace the raw-JSON minimal launcher)

## Goal (one sentence)
Render the run launcher as a typed form built from the workflow's declared params (labels, types,
help, options, and **pre-filled declared defaults**), replacing the raw-JSON "Params (JSON object)"
textarea.

## Why
The current "minimal launcher" makes the user hand-write a JSON params object and does not apply
declared defaults — so a workflow that reads a defaulted param (e.g. `ctx.params["duration_s"]`,
default 30) crashes when the user omits it, and there is no friendly way to type a topic. #97 now
exposes each workflow's declared params on `/api/workflows`; use them.

## What to change

### 1. `frontend/src/types.ts`
Add a `Param` type and put `params` on `Workflow`:
```ts
export type ParamType =
  | "text" | "textarea" | "number" | "bool" | "select" | "multiselect" | "file";

export type Param = {
  key: string;
  type: ParamType;
  label: string;
  required: boolean;
  default: unknown;
  help: string | null;
  affects_cost: boolean;
  min: number | null;
  max: number | null;
  step: number | null;
  options: unknown[] | null;
  options_from: string | null;
  placeholder: string | null;
  unit: string | null;
};
```
Add `params: Param[];` to the `Workflow` type (after `quality_factors`).

### 2. `frontend/src/components/WorkflowCard.tsx`
Pass the declared params to the form: add `params={workflow.params}` to the `<RunLaunchForm .../>`.

### 3. `frontend/src/components/RunLaunchForm.tsx` — the typed form
- Add `params: Param[]` to `RunLaunchFormProps` and accept it.
- Keep the existing **Video count** and **Concurrency** number fields and the submit/cancel flow.
- REMOVE the raw-JSON textarea, `parseParamsObject`, and the `paramsText` state.
- Change the eyebrow from "Minimal launcher" to `Launch`, and drop the "Temporary controls…" note.
- Build initial form state from the declared params, one entry per `param.key`, seeded from
  `param.default` coerced to the field's shape:
  - text / textarea / select → `String(default ?? "")`
  - number → `default` as a number when finite, else `""` (store as string in the input, parse on submit)
  - bool → `Boolean(default)`
  - multiselect → an array of strings (`default` if it is an array of strings, else `[]`)
  - file → unsupported here (see below)
- Render one control per param IN ORDER, each wrapped in the existing `.field` with a
  `.field-label` (append the `unit` in parentheses when present, and a `*` when `required`), the
  control, and — when `param.help` is set — a `<span className="field-help">` below it (add a small
  `.field-help` rule to `index.css`: `font-size: 11.5px; color: var(--text-faint);`). Controls:
  - **text** → `<input className="field-input" type="text" placeholder={param.placeholder ?? ""}>`
  - **textarea** → `<textarea className="field-input field-textarea" rows={4}>`
  - **number** → `<input className="field-input" type="number">` with `min`/`max`/`step` from the
    param when non-null
  - **bool** → `<input type="checkbox">` (label beside it; you may use a `.field-check` wrapper —
    add minimal CSS `display:flex; gap:8px; align-items:center;` if needed)
  - **select** → `<select className="field-input">` with one `<option>` per `param.options`
    (value + label = `String(option)`); if `required` is false prepend an empty option labelled
    "— none —".
  - **multiselect** → a checkbox per `param.options`; toggling updates the string array.
  - **file** OR a **select/multiselect whose `options` is null** (e.g. dynamic `options_from`) →
    graceful fallback: render a `<input type="text" className="field-input">` and a help note
    "Enter value(s) manually." so nothing is un-fillable. (No current workflow needs this; keep it
    simple and safe.)
- On submit, build `params: Record<string, unknown>`:
  - text / textarea / select → the string value (send as-is, including "" for an untouched optional
    field — this guarantees the workflow never sees a missing key)
  - number → `Number(value)`; if the field is blank, omit that key ONLY if `!required`, else error
    "…is required."; reject `NaN` with an error naming the field's label
  - bool → the boolean
  - multiselect → the string array
  - Validate required text/select fields are non-empty (trimmed) → error "`<label>` is required."
- Pass the built object as `params` to `startRun` (unchanged signature). Keep the existing
  video-count / concurrency integer validation.

Reuse existing classes (`.panel`, `.launch-panel`, `.panel-head`, `.panel-body`, `.launch-form`,
`.field`, `.field-label`, `.field-input`, `.field-textarea`, `.form-error`, `.card-foot`,
`.launch-actions`, `.btn` variants, `.eyebrow`, `.launch-title`, `.page-note`). Only add the tiny
`.field-help` (and, if used, `.field-check`) rules to `index.css`, using existing CSS variables.

## Constraints / do-nots
- Touch ONLY `frontend/src/types.ts`, `frontend/src/components/WorkflowCard.tsx`,
  `frontend/src/components/RunLaunchForm.tsx`, and `frontend/src/index.css`.
- Do NOT write into `app/web/` or touch `app/web/.gitkeep`; do not commit built assets.
- No `any`; keep the React 19 + hooks idiom. Keep `npm run lint` / `npm run typecheck` clean.

## Design follow-up (SECOND delegation — four small polish fixes)
Your first implementation passed design review with no blockers. Apply these four polish items:

1. **Dark native widgets.** The launcher introduces the app's first native `<input type="checkbox">`
   and `<select>`, which render in the browser's light styling on the dark UI. Add
   `color-scheme: dark;` to the `:root` rule in `frontend/src/index.css` (one line, near the top with
   the other `:root` declarations) so native controls theme dark app-wide.
2. **Bool field double label.** In `RunLaunchForm.tsx`, the bool case renders the label twice — once
   in `.field-label` (via `controlLabel`) and again in the checkbox's `<span>{param.label}</span>`.
   Drop the outer `.field-label` span for the bool case (keep the `.field-check` label with the
   checkbox + `param.label`; if the param has a `unit` or is `required`, you may append that marker to
   the checkbox's span text instead). No duplicate label text.
3. **Enforce required multiselect.** In `collectParams`, a `required` multiselect must error when the
   selected array is empty: `if (param.required && selected.length === 0) return { ok:false, error:
   \`${param.label} is required.\` }`. (Otherwise the `*` marker promises a constraint the form never
   enforces.)
4. **`aria-required`.** Add `aria-required={param.required}` to each required-capable control
   (text/textarea/number/select inputs, and the manual-fallback input) so assistive tech announces
   requiredness.

Keep everything else. Touch only `RunLaunchForm.tsx` and `index.css`. Keep lint/typecheck/build clean.

## Review B follow-up (THIRD delegation — three correctness fixes in `RunLaunchForm.tsx`)
Cross-family review found three real form-logic gaps. Apply all three (touch ONLY
`RunLaunchForm.tsx`):

A. **Manual multiselect must submit an array, not a string.** `usesManualInput` is true for a
   multiselect with no `options` (dynamic `options_from`), and the manual branch of `collectParams`
   currently stores a plain string — violating the `string[]` contract. In the manual branch, when
   `param.type === "multiselect"`, parse the text into an array:
   `text.split(",").map((s) => s.trim()).filter((s) => s !== "")`, require non-empty when
   `param.required` (error `\`${param.label} is required.\``), and store the array; otherwise keep the
   string behaviour for text/select/file. (The manual field's help already says "Enter value(s)
   manually" — a comma-separated list is the intended entry.)

B. **Reseed values for newly-declared params without wiping input.** `values` is seeded once via the
   `useState` initializer, so if `params` changes while the launcher is open (a folder rescan), a
   newly-declared param submits blank. Add `useEffect` (import it) keyed on `[params]` that merges a
   seed for any `param.key` NOT already present in `values`, leaving existing entries untouched:
   ```ts
   useEffect(() => {
     setValues((current) => {
       let changed = false;
       const next = { ...current };
       for (const param of params) {
         if (!(param.key in current)) { next[param.key] = seedValue(param); changed = true; }
       }
       return changed ? next : current;
     });
   }, [params]);
   ```

C. **Required select with no default must show an explicit placeholder.** A required `select` seeded
   to `""` has no matching option, so the browser silently displays the first real option while the
   form still treats it as unselected — the user sees a value but submit says "required". For a
   required select, render a `<option value="" disabled>— select —</option>` as the first option
   (keep the existing `<option value="">— none —</option>` for optional selects). This forces a real
   choice and keeps the `*`/required validation honest.

Keep everything else and the four polish fixes. Keep lint/typecheck/build clean.

## Scope
- `frontend/src/types.ts`
- `frontend/src/components/WorkflowCard.tsx`
- `frontend/src/components/RunLaunchForm.tsx`
- `frontend/src/index.css`

## Verify (from the worktree)
- `cd frontend && npm run lint` → clean.
- `cd frontend && npm run typecheck` → clean.
- `cd frontend && npm run build` → succeeds (do NOT commit the `app/web/` output).
- `cd frontend && npm run format:check` and `npm run stylelint` → fix anything your new lines flag
  (pre-existing failures on RunRecordView.tsx / VideoPanel.tsx are not yours).
