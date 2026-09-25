# TASK-SSN-A5 — library upload endpoint (multipart)

Add `POST /api/library/assets` so the owner can upload an audio asset (music / SFX / voice) into the owner pool, tagged and granted. Pinned by `tests/api/test_library_upload.py` (make it green without editing it). `python-multipart==0.0.32` is already installed and pinned in `requirements.txt`.

## What to implement (in `app/api/library.py`)

Add a module-level constant `_MAX_UPLOAD_BYTES = 25 * 1024 * 1024` (25 MiB) and the endpoint:

**`POST /api/library/assets`** — a multipart form:
- `file`: the uploaded audio (`UploadFile`).
- `name`: str (form field) — the asset's alias/name.
- `kind`: str (form field) — one of `music` / `sfx` / `voice` (reject anything else, 422).
- `grant`: str (form field) — a JSON string, either `{"all": true}` or `{"workflows": [ids]}`.
- `mood`, `energy`: optional str form fields (open facets).

Behaviour, in order:
1. **Validate the media type**: accept only audio — `file.content_type` starting with `audio/` OR a filename extension in `.mp3/.wav/.m4a/.ogg`. Reject otherwise with HTTP 415 (before reading the body).
2. **Validate `kind`** in {music, sfx, voice} (422 otherwise) and **validate `grant`**: `json.loads` it, then run it through the grant shape check (reuse `GrantStore`'s validation — e.g. call the same validator, or attempt `set_grant` only AFTER the file is stored; but reject a malformed grant with 400/422 BEFORE storing anything). A `GrantError`/`json` error -> 400 or 422.
3. **Stream to a temp file with the cap enforced DURING streaming** (do NOT read the whole upload into memory then check): read `file` in chunks (e.g. 64 KiB) into a `tempfile.NamedTemporaryFile`, tracking cumulative bytes; if it exceeds `_MAX_UPLOAD_BYTES`, stop reading, delete the temp file, and raise HTTP 413 — nothing is stored. (This is the Issue-11 control: the test asserts an oversize upload yields 413 and writes no asset.)
4. **Store**: owner root = `request.app.state.library_dir / "_owner"`. `LibraryStore(owner_root, facets=(FacetSpec("mood"), FacetSpec("energy"))).put(name, temp_path, kind=kind, facets={...only mood/energy that were given...})` — content-addressed by hash; the client filename is NEVER used as a path. Then `GrantStore(owner_root).set_grant(asset.id, grant)`. Remove the temp file.
5. **Return the created asset row** (200 or 201), same shape as `GET /api/library/assets` returns per asset: `{id, kind, status, facets, description, grant}` (grant = the one just set).

Reuse the existing per-asset row builder from the GET endpoint if you factored one; otherwise build the row the same way. Import `FacetSpec`/`LibraryStore` from `sfvf.library`, `GrantStore`/`GrantError` from `sfvf.grants`. The global CSRF guard already protects this POST (same-origin); no token handling here.

## Scope

- `app/api/library.py`

Touch nothing else (the SDK, other app files, tests, docs, handoff, CI, requirements are all already handled). Do NOT add dependencies.

## Constraints

- Workspace boundary; ASCII; one paragraph is one line.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/api/test_library_upload.py -q` passes (5).
- No regression: `./.venv/Scripts/python.exe -m pytest tests/api -q` (the two pre-existing failures in test_clear_runs.py / test_learning_run_api.py are unrelated — ignore them).
- `./.venv/Scripts/python.exe -m ruff check app/api/library.py` and `./.venv/Scripts/python.exe -m mypy app/api/library.py` are clean.
- Print the files you changed and a one-paragraph summary.
