# TASK F1c — the Settings tab UI (removes the placeholder)

Completes R-066 (UI) and R-068 (UI); replaces the §8.7 placeholder. RED-first: the frozen test
`frontend/src/components/SettingsView.test.tsx` exists and is RED. **Do NOT edit that test.**
Read it first — it defines the exact accessible hooks you must expose.

## 1. API client — frontend/src/api.ts (+ types in frontend/src/types.ts)
Add, matching the existing fetch-wrapper style (throw on !response.ok):
- `fetchSettings(): Promise<SettingsData>` — GET /api/settings. `SettingsData` =
  `{ providers: {id,label,secret_names:string[],configured:boolean}[]; configured_secret_names: string[];
     allowed_secret_names: string[]; defaults: Record<"silence_limit_seconds"|"default_concurrency"|
     "default_step_concurrency"|"cache_max_bytes", {effective:number; source:"env"|"stored"|"default"}> }`.
- `putSecret(name: string, value: string): Promise<void>` — PUT /api/settings/secrets/{name} body {value}.
- `deleteSecret(name: string): Promise<void>` — DELETE /api/settings/secrets/{name}.
- `putDefaults(fields: Partial<Record<...the four keys..., number>>): Promise<void>` — PUT /api/settings/defaults.
(POST/PUT/DELETE go through the same origin; the app's csrf_guard allows same-origin — mirror how
other mutating helpers in api.ts call fetch.)

## 2. Component — frontend/src/components/SettingsView.tsx
Model it on frontend/src/components/LibraryView.tsx (load on mount, loading/loaded/error states,
Retry). Sections and required accessible hooks (the frozen test asserts these exact names):
- **API keys**: one row per `allowed_secret_names` entry (label it with the provider label when the
  name belongs to a provider, else the raw name), showing configured vs missing. Each row has a
  write-only text input with accessible name `Set <NAME>` (value always starts empty — NEVER show a
  stored value) and a button `Save <NAME>` that calls `putSecret(NAME, value)` then refetches. When
  the name is in `configured_secret_names`, also render a button `Clear <NAME>` that calls
  `deleteSecret(NAME)` then refetches.
- **Connections**: a genuine empty state, e.g. "No service connections require sign-in." (No MCP
  provider exists — this is real content, not a placeholder component.)
- **Global defaults**: number inputs labelled exactly `Step silence limit (seconds)`,
  `Default concurrency`, `Default step concurrency`, `Max cache size (bytes)`, pre-filled with each
  field's `effective` value. Show each field's `source`; when `source === "env"`, render that field
  read-only with a short note that an environment variable is overriding it. A button named
  `Save defaults` (matches /save.*default/i) calls `putDefaults({...changed numeric fields...})`
  then refetches. Send numbers, not strings.
- **error**: on a load failure, show a message and a button named `Retry` that refetches.
- Observability: no `console.error` in any state; never render `undefined` / `NaN` / `[object Object]`.
- Follow the house design sense (design-auditor will check): consistent with the other tabs' look;
  the design detector should report no primary findings.

## 3. Wire it in + remove the stand-in
- frontend/src/App.tsx: render `<SettingsView />` for the `settings` tab instead of
  `<PlaceholderView tab={tab} />`.
- DELETE frontend/src/components/PlaceholderView.tsx and remove its import from App.tsx (and any
  other reference / its test if one exists). After this, no `PlaceholderView*` component and no
  "Arrives in a later stage" string remain in shipped code (completion-check --mode done must find
  no stand-in for the Settings tab).

## Done when
- `npm --prefix frontend run test -- SettingsView` passes (all cases).
- `npm --prefix frontend run test` (full vitest) passes; `npm --prefix frontend run lint` and
  `npm --prefix frontend run typecheck` are clean.
- `python ~/.claude/cursor-bridge/completion-check.py --mode done` shows NO stand-in for R-066/R-068
  (PlaceholderView gone). Frozen test file unmodified.
- End with an `Assumed, not verified` list (or `none`).
