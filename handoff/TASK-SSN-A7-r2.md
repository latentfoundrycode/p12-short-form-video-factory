# TASK-SSN-A7-r2 — Full asset metadata model + accessible Library tab

Evolve the current (in-tree, uncommitted) Library-tab implementation to the "Full" model the owner chose. Follow design `docs/DESIGN-sensational-science-news.md` §22 (rev 7) and the amended mockup `docs/mockups/library-tab.html` (read it). Make the updated frozen tests green without editing them: `tests/api/test_library_api.py`, `tests/api/test_library_upload.py`, `tests/api/test_library_mutations_api.py`, `frontend/src/components/LibraryView.test.tsx` (and keep the existing SDK/api tests green).

## Model (rev 7)

- Mood/Energy are MULTI-VALUE, stored as the asset's `tags` tuple with prefixes `mood:` / `energy:` (e.g. `tags = ("mood:ominous", "mood:mysterious", "energy:building")`). The `kind` (music/sfx/voice) stays the LibraryStore `kind`. The generic single-valued `facets` field is GONE from the owner-asset row.
- The asset ROW (GET list, upload, edit) is now: `{id, name, kind, status, mood: string[], energy: string[], description, grant}` — mood/energy are the prefix-stripped tag values.
- Rename = change the asset's alias. Re-kind = change the asset's `kind`. Both editable after upload.

## Part 1 — SDK (`sdk/sfvf/library.py`)

- Keep the public `name_for(asset_id)` (reverse alias) added earlier.
- Add `rename(asset_id, name)`: update `aliases.json` so `name -> asset_id` (remove any existing alias pointing at this id first, then set the new one). Atomic write.
- Support changing `kind` and `tags` on an existing asset (metadata-only sidecar rewrite + catalogue refresh, mirroring the existing status-flip / annotate pattern). Either extend `annotate` to also accept `kind` and `tags`, or add `set_kind(id, kind)` / `set_tags(id, tags)`. Add SDK unit tests for rename + kind/tags change (a new tests/sdk file you create is fine — you may add tests for code you write here, but do NOT edit the supervisor-authored frozen tests listed above).

## Part 2 — backend endpoints (`app/api/library.py`)

- `_asset_row`: return `{id, name, kind, status, mood, energy, description, grant}` where `mood`/`energy` are the values of the asset's `mood:`/`energy:`-prefixed tags (prefix stripped). Remove the `facets` field.
- Upload `POST /assets`: accept `mood` and `energy` as JSON-array form fields; store them as prefixed tags via `put(..., tags=[...])`. Keep name(alias)/kind/grant/streaming-cap/type-validation as they are.
- Edit `PUT /assets/{id}`: accept optional `name` (rename), `kind` (re-kind), `mood` (list), `energy` (list), `caveats`; apply rename + re-kind + replace the mood:/energy: tags + set caveats; return the updated row. Keep the 64-hex id validation + resolve-first 404 + malformed-input 422.

## Part 3 — frontend

- `frontend/src/types.ts`: `LibraryAsset` becomes `{ id: string; name: string | null; kind: string; status: string; mood: string[]; energy: string[]; description: string; grant: LibraryGrant }` (drop `facets`).
- `frontend/src/api.ts`: `uploadLibraryAsset` sends `mood`/`energy` as JSON arrays; the edit helper (`annotateLibraryAsset` or a renamed `updateLibraryAsset`) PUTs `{name?, kind?, mood?, energy?, caveats?}`.
- `frontend/src/components/LibraryView.tsx`:
  - Render mood/energy as arrays; persist ALL chips (not just the first). Save sends name (rename), kind (re-type), mood[], energy[], caveats.
  - CHIP ACCESSIBILITY (design-auditor BLOCKING + the frozen a11y test): each chip is focusable and has a real delete `<button>` with an accessible name that references the tag (e.g. `aria-label="remove wonder"`), plus a keyboard EDIT path (Enter/F2 on the focused chip). KEEP the right-click Edit/Delete menu, but make it an ADDITION — Escape-dismissible with focus moved into it. The frozen `LibraryView.test.tsx` finds a `button` whose accessible name matches the tag, clicks it, and expects the chip removed with no console.error.
  - Keep the empty/error(Retry, handled)/dense states and the access picker.
- `frontend/src/index.css`: add the `.chip-x` styling (see the mockup) consistent with the tokens; do not restyle other views.

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

(You MAY also add a new tests/sdk/*.py for the SDK methods you add.) Do NOT run `npm run build` (no app/web changes). Do NOT modify the frozen tests above, `docs/`, `handoff/`, CI, or dependencies.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- Backend: `./.venv/Scripts/python.exe -m pytest tests/api tests/sdk -q` — the Full-model contracts pass; the only failures are the two pre-existing unrelated ones (test_clear_runs unsafe-run-id, test_learning_run unknown-workflow-404).
- Frontend: `npm --prefix frontend run test` (incl. LibraryView.test.tsx a11y test), `npm --prefix frontend run lint`, `npm --prefix frontend run typecheck` all clean.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/library.py app/api/library.py` and project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary.
