# TASK-SSN-A7 — Library tab UI (+ asset display name in the row)

Deliver the owner-facing Library tab, matching the approved mockup `docs/mockups/library-tab.html` (read it for the exact look and interactions). Pinned by two frozen tests: `tests/api/test_library_api.py::test_assets_row_includes_display_name` (backend) and `frontend/src/components/LibraryView.test.tsx` (frontend). Make both green without editing them.

## Part 1 — backend: add the display `name` to the asset row

The asset's friendly name is its alias (set at `put(name=...)`). Surface it:
- `sdk/sfvf/library.py`: add a PUBLIC method `LibraryStore.name_for(asset_id: str) -> str | None` that returns an alias pointing at `asset_id` (reverse lookup of `aliases.json`; return any one, or the first deterministically; None if no alias). Reuse `_load_aliases`.
- `app/api/library.py`: add `name: str | None` to the `LibraryAssetOut` model and have `_asset_row` populate it via `name_for(asset.id)` (the `_asset_row` helper takes what it needs — pass the store or the name). Every asset row (GET list, upload, mutations) now carries `name`.

`tests/api/test_library_api.py::test_assets_row_includes_display_name` asserts the seeded asset's row has `name == "cosmic.mp3"` (its alias).

## Part 2 — frontend: the Library tab

Match `docs/mockups/library-tab.html`. Reuse the existing design system (tokens + `.panel`/`.btn`/`.field`/`.pill`/`.li` classes in `frontend/src/index.css`); add only the new classes the mockup introduces (tag-input chips, the access picker). Files:

- `frontend/src/tabs.ts`: add `{ id: "library", label: "Library" }` to `TABS` (place it per the mockup's tab order — after Schedule).
- `frontend/src/components/Shell.tsx`: add a `case "library"` to `TabIcon` returning an inline SVG (a simple library/collection glyph). The switch is exhaustive over `TabId`, so TypeScript requires it.
- `frontend/src/App.tsx`: add `: tab === "library" ? <LibraryView />` to the view ladder.
- `frontend/src/types.ts`: add a `LibraryAsset` type `{ id: string; name: string | null; kind: string; status: string; facets: Record<string,string>; description: string; grant: LibraryGrant }` and `LibraryGrant = { all: true } | { workflows: string[] }`, plus a `LibraryWorkflow = { id: string; label: string }`.
- `frontend/src/api.ts`: add typed helpers (same fetch style as the existing helpers):
  - `fetchLibraryAssets(): Promise<LibraryAsset[]>` (GET `/api/library/assets`, returns `.assets`).
  - `fetchLibraryWorkflows(): Promise<LibraryWorkflow[]>` (GET `/api/library/workflows`, returns `.workflows`).
  - `uploadLibraryAsset(form: FormData): Promise<LibraryAsset>` (POST `/api/library/assets`, multipart).
  - `setLibraryGrant(id, grant): Promise<LibraryAsset>` (POST `/api/library/assets/{id}/grant`).
  - `annotateLibraryAsset(id, body): Promise<LibraryAsset>` (PUT `/api/library/assets/{id}`).
  - `deactivateLibraryAsset(id)` / `reactivateLibraryAsset(id)` (POST the respective routes).
- `frontend/src/components/LibraryView.tsx`: the view. Follow the Learning tab's pattern (`LearningView.tsx`): a self-contained function component that fetches on mount, holds `status: "loading" | "ready" | "error"` + data, and returns `<section className="view on">`. It must render:
  - **Assets list** (left panel): a row per asset showing NAME, a kind pill (music/sfx/voice), mood·energy facets, and an ACCESS SUMMARY — "All workflows" for `{all:true}`, the single workflow's label for one id, or "N workflows" for several; a hidden (inactive) asset is shown greyed/marked.
  - **Detail / edit** (right panel) for a selected asset: a **Type dropdown** (`<select>` music/sfx/voice), **Mood** and **Energy** as **tag inputs** (typing text + a comma commits a rounded chip; right-click a chip → Edit (in-place input, box kept) / Delete — implement the interaction as in the mockup's inline script), a caveats field, and an **access picker** (radio: All workflows / Specific → a checkbox list of workflows from `fetchLibraryWorkflows`), with Save / Hide (deactivate) actions wired to the api helpers.
  - **Add asset** flow: an upload form (file + name + type + mood/energy + access) posting via `uploadLibraryAsset`; voice guidance per the mockup ("a clean ~20-60 s voice sample; the AI clones it").
  - **Empty state**: a "No assets yet" message (videos are narration-only until assets are added).
  - **Error state**: a load-failure message with a **Retry** button; the failure is HANDLED in the UI (do NOT let it reach `console.error`).
- `frontend/src/index.css`: add the tag-input/chip, access-picker, and any Library-specific classes, consistent with the tokens (see the mockup's `<style>` for exact values). Do NOT restyle other views.

## Frontend observability + design acceptance (`LibraryView.test.tsx`, design-auditor)

- The three inventory states (dense / empty / error) render through the real component; **no `console.error`** in any state; nothing renders as `undefined` / `NaN` / `[object Object]`.
- The dense state shows each asset's name + kind + access summary; `{all:true}` reads as "All workflows"; a specific grant names the workflow.
- Design: matches the mockup (`design-auditor` will check fidelity + the frozen `vercel-interface.mdc` interaction/forms items).

## Scope

- sdk/sfvf/library.py
- app/api/library.py
- frontend/src/tabs.ts
- frontend/src/components/Shell.tsx
- frontend/src/App.tsx
- frontend/src/components/LibraryView.tsx
- frontend/src/api.ts
- frontend/src/types.ts
- frontend/src/index.css

Do NOT build `app/web/` (no `npm run build`; frontend tests run under vitest/jsdom without a build — the single app/web build happens later at packaging). Do NOT modify tests, other files, `docs/` (read the mockup, don't edit it), `handoff/`, CI, or dependencies.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in any Markdown.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/api/test_library_api.py -q` passes (incl. the name test); no backend regression `./.venv/Scripts/python.exe -m pytest tests/api tests/sdk -q` (the two pre-existing `tests/api` failures are unrelated).
- `npm --prefix frontend run test` passes (incl. `LibraryView.test.tsx`); `npm --prefix frontend run lint` and `npm --prefix frontend run typecheck` are clean.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/library.py app/api/library.py` and the project `./.venv/Scripts/python.exe -m mypy` are clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary.
