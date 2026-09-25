# TASK-SSN-A2 — owner-pool access grants store (`sfvf.grants`)

Add per-asset access control for the owner library pool: an owner-uploaded asset (music / SFX / voice) can be granted to ALL workflows or a chosen SET of specific workflows. This increment is the pure storage + validation primitive; the app endpoints (A3/A6) and the workflow read-path (A4) build on it.

## What to implement

Create `sdk/sfvf/grants.py` with a `GrantStore` class and a `GrantError` exception, pinned by the frozen test `tests/sdk/test_grants.py` (make it green without editing it):

- `class GrantError(ValueError)` — raised on a malformed grant.
- `class GrantStore:` constructed with one argument, the owner-pool root directory (`GrantStore(root: Path)`); grants live in `root / "grants.json"` (a mutable id -> grant map, shape like the library's `aliases.json`).
- `set_grant(self, asset_id: str, grant: <dict>) -> None` — validate the grant shape, then persist it atomically to `grants.json` (create the file/dir on first write; overwrite an existing grant for the same id).
- `get_grant(self, asset_id: str) -> dict` — return the stored grant, or the DEFAULT-DENY `{"workflows": []}` when the asset has no grant.
- `grant_allows(self, asset_id: str, workflow_id: str) -> bool` — True iff the grant is `{"all": True}`, or `workflow_id` is in the grant's `workflows` list; otherwise False (including for an ungranted asset).

Grant shape (the ONLY two valid forms — anything else raises `GrantError`):
- `{"all": true}` — `all` must be a bool.
- `{"workflows": [<str>, ...]}` — `workflows` must be a list of strings.
- Exactly one form: a dict with both keys, neither key, extra keys, a non-dict, or non-string workflow ids are all invalid.

Storage details:
- Persist atomically (reuse the existing atomic-write helper `_write_json_atomic` from `sdk/sfvf/cache.py`, as `library.py` does) so a crash never leaves a torn `grants.json`.
- Because the APP writes `grants.json` (out of any run) while a workflow run may be reading it, the atomic write must tolerate a Windows sharing violation: wrap the replace in a short bounded retry (a few attempts with a tiny sleep) and only then re-raise. The read path (`get_grant`) opens/reads/closes briefly.
- A grant may reference a workflow id that no longer exists; store and read it back untouched (allow-checks for other workflows simply return False).

Keep it small, stdlib-only, consistent with the style of `sdk/sfvf/library.py` / `sdk/sfvf/cache.py`. ASCII only; one paragraph is one line.

## Scope

- `sdk/sfvf/grants.py` (new file).

Touch nothing else. Do NOT modify any test, `sdk/sfvf/library.py`, anything under `docs/` or `handoff/`, `.env`, `secrets/`, or CI. Do NOT add dependencies.

## Constraints

- Workspace boundary: read/write only inside this `Workspace/` checkout.
- Record any tooling friction or a defect in `docs/BUILDER_NOTES.md`.

## Revision r2 — fail-closed hardening (Review A + security-auditor)

Four more frozen tests were added to `tests/sdk/test_grants.py`; make them green too, in `sdk/sfvf/grants.py` only:

1. **`get_grant` must return a FRESH default-deny object each call** — do NOT return an alias of a shared module-level constant. A caller that mutates the returned `{"workflows": []}` list must not affect any later `get_grant`. (Return a new `{"workflows": []}` literal, not `dict(_DEFAULT_DENY)` where the list is shared.)
2. **`get_grant` fails CLOSED on a corrupt grants.json** — if the file is unparseable or not a JSON object, `get_grant` returns default-deny `{"workflows": []}` (it must NOT raise, and must NOT allow). Catch the parse/type error inside `get_grant`.
3. **`get_grant` validates each stored entry on read** — run the stored grant for the requested id back through the same shape validation; if the stored entry is invalid (e.g. a hand-edited `{"all": true, "workflows": [...]}`), treat it as default-deny for that id (do not return the invalid shape). This is defense-in-depth so the write-path is not the only guarantee.
4. **`set_grant` must FAIL LOUD on a corrupt grants.json** — writing must raise `GrantError` (not silently overwrite and lose existing grants) and must leave the corrupt file untouched. (So the load path used by `set_grant` raises `GrantError` on a corrupt file, while `get_grant` catches that and denies.)

Keep the semantics coherent: reads deny on corruption/invalidity; writes raise on corruption. Suggest a shared internal loader that raises `GrantError` on a corrupt/non-object file, with `get_grant` wrapping it (plus per-entry validation) to return default-deny, and `set_grant` letting it propagate.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_grants.py -q` passes.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/grants.py` and `./.venv/Scripts/python.exe -m mypy sdk/sfvf/grants.py` are clean.
- Print the files you changed and a one-paragraph summary.
