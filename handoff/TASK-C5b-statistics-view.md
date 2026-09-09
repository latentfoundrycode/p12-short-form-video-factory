# TASK C-5b — Statistics tab frontend (PRD §8.6, §7.1)

## Goal (one sentence)
Replace the Statistics placeholder with a real view that fetches `GET /api/statistics` and renders
spend-over-time per meter, conforming to the approved mockup, with each meter shown separately and
credit meters never combined.

## Context (already built, do not change)
- Backend `GET /api/statistics?months=N` (C-5a) returns:
  ```json
  {"months": 6, "series": [
    {"id":"fiat","kind":"fiat","label":"Fiat currency","providers":["OpenRouter"],"unit":"usd",
     "total":0.42,"buckets":[{"month":"2026-04","amount":0.0}, ... one per window month ascending]},
    {"id":"higgsfield","kind":"credit","label":"Higgsfield","providers":["Higgsfield"],
     "unit":"credits","total":96.0,"buckets":[...]}
  ]}
  ```
  `series` is `[]` when there is no spend. Fiat is first when present, then credit series by label.
- The approved design is `docs/SFVF_UI_Mockup.html`, section `id="v-stats"` (≈ lines 864–942) and the
  `.chart` / `.bar` CSS (≈ lines 488–491). Match its structure and classes.

## Changes

### 1. `frontend/src/types.ts` — add types (place near the other API types)
```ts
export type StatBucket = { month: string; amount: number };
export type StatSeries = {
  id: string;
  kind: "fiat" | "credit";
  label: string;
  providers: string[];
  unit: string;
  total: number;
  buckets: StatBucket[];
};
export type Statistics = { months: number; series: StatSeries[] };
```

### 2. `frontend/src/api.ts` — add a fetch function (mirror `fetchRuns` style)
```ts
export async function fetchStatistics(months?: number): Promise<Statistics> {
  const qs = months ? `?months=${encodeURIComponent(months)}` : "";
  const response = await fetch(`/api/statistics${qs}`);
  if (!response.ok) throw new Error(`Could not load statistics (${response.status})`);
  const data = (await response.json()) as Statistics;
  if (!Array.isArray(data.series)) throw new Error("Unexpected statistics response");
  return data;
}
```
Import `Statistics` in the type import block.

### 3. `frontend/src/components/StatisticsView.tsx` — NEW component
Follow the exact loading/ready/error idiom of `WorkflowGrid.tsx` (a `status: "loading" | "ready" |
"error"` state, fetch-on-mount inside `useEffect` with a `cancelled` guard, a Retry button on error).
- Props: none (self-contained), OR `{}`; it manages its own state.
- **Period selector** in the `.page-head` (a `<select className="sel">`), options: `Last 6 months`
  (value 6), `Last 12 months` (value 12), `Last 24 months` (value 24). Changing it refetches with
  that `months`. Default 6. (The mockup's "This year"/"Last 30 days" are approximated by month
  windows — months is the only backend axis.)
- Page head: title "Statistics"; note exactly
  `Meters are shown separately and never combined. Credits from different providers are not comparable.`
- Body: a `<div className="stack">`. For EACH series render a `<div className="panel">` with:
  - `.panel-head` containing a left block with `<span className="eyebrow">` = for fiat
    `"Fiat currency"`, for credit `` `Credits · ${label}` ``; and below it the formatted total in a
    mono line (`style={{ fontFamily: "var(--font-mono)", fontSize: 17, marginTop: 3 }}`).
    For a fiat series ALSO render a right-side `<span className="pill">` listing the providers
    (join with ", ").
  - `.panel-body` containing a `<div className="chart">` with one `<div className="bar">` per bucket:
    an inner `<i>` whose `style.height` is a percentage of the series' max bucket amount
    (`amount / max * 100`, clamped; when max is 0 render a flat minimal bar), and a `<span>` with the
    month label abbreviated to the 3-letter uppercase month (e.g. `2026-07` → `JUL`).
- **Amount formatting** (a small local helper): show the real unit — do NOT invent an FX conversion.
  - `usd` → `$` + amount with 2 decimals (e.g. `$0.42`).
  - `credits` → integer-grouped amount + ` cr` (e.g. `96 cr`).
  - any other unit → grouped amount + ` ` + unit.
  Use `toLocaleString` for grouping. Keep it a pure function.
- **Empty state** (`series.length === 0`, ready): a single `.panel` > `.panel-body` > `.page-note`
  reading that no spend has been recorded yet (an empty Statistics tab is a valid state — do NOT
  fabricate demo data; cf. the sparseness-is-expected principle).

### 4. `frontend/src/App.tsx` — route the tab
Render `<StatisticsView />` when `tab === "statistics"` (and not in a run), before the
`PlaceholderView` fallback. Import it.

### 5. `frontend/src/components/PlaceholderView.tsx` — drop "statistics"
Remove `"statistics"` from the `Exclude<TabId, "workflows">` maps (`LINES`, `TITLES`) and the prop
type, so the remaining placeholders are `schedule | learning | settings`. (App only passes those now.)

### 6. `frontend/src/index.css` — port the chart/layout classes from the mockup
Add (values from `docs/SFVF_UI_Mockup.html`), if not already present:
```css
.stack { display: flex; flex-direction: column; gap: 16px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
@media (max-width: 960px) { .two { grid-template-columns: 1fr; } }
.sel { background: var(--surface-2); color: var(--text); border: 1px solid var(--line);
  border-radius: var(--r); padding: 6px 10px; }
.chart { display: flex; align-items: flex-end; gap: 7px; height: 104px; padding-top: 8px; }
.bar { flex: 1 1 0; display: flex; flex-direction: column; justify-content: flex-end;
  align-items: center; gap: 6px; height: 100%; }
.bar i { width: 100%; background: var(--surface-3); border-radius: 1px 1px 0 0;
  border-top: 1.5px solid var(--text-dim); }
.bar span { font-family: var(--font-mono); font-size: 9.5px; color: var(--text-faint); }
```
(You need `.stack`, `.sel`, `.chart`, `.bar`; `.two` only if you use the two-column grid. `.panel`,
`.panel-head`, `.panel-body`, `.eyebrow`, `.pill`, `.page-*` already exist.) Keep stylelint-clean.

## Constraints / do-nots
- Do NOT add any dependency (no chart library — the bars are plain divs). React 19 + Vite only.
- Do NOT invent currency conversion or fabricate data. Show the unit the backend returns.
- Do NOT edit `app/web/` (build output) or any backend file.
- Match the existing component style (function components, no classes; `void promise.then(...)` for
  fire-and-forget; typed props). Keep `eslint`, `tsc`, and `prettier --check` clean.

## Verify (from `frontend/` in the worktree)
- `npm run typecheck` → no errors.
- `npm run lint` → no errors.
- `npm run format:check` → clean (run `npm run format` if needed).
- `npm run stylelint` → clean.
- `npm run build` → succeeds (emits into `../app/web`).
The supervisor will additionally verify in-browser against a seeded runs dir.
