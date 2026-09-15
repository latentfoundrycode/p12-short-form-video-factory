# TASK — in-app rules/skills editor: backend (list instructions + save-with-archive)

## Goal (one sentence)
Add a shared single-file edit helper and two Learning-API endpoints so the frontend can list a
workflow's rule/skill files and save a hand-edited one through the same archive-and-version-bump
path acceptance already uses.

## Why
The Learning tab must let the user open a workflow's own `rules/*.md` and `skills/*.md` files, edit
one by hand, and save it. A manual save has to archive the prior version and bump the frontmatter
`version` exactly like accepting an optimiser proposal (Architecture §5.11), so the provenance
record ("which instructions produced which past video") stays accurate no matter who made the edit.

## Frozen contract (already committed — do NOT edit)
- `tests/core/test_learning_edit.py` — the `apply_instruction_edit` helper.
- `tests/api/test_learning_edit_api.py` — the two endpoints.
All existing tests (especially `tests/core/test_learning_accept.py`) must stay green.

## What to change

### 1. `app/learning/accept.py` — extract a shared edit helper
Add a public function that archives + bumps + writes ONE file, and refactor `accept_learning` to use
it so behaviour is byte-for-byte identical:

```python
def apply_instruction_edit(workflow_dir: Path, relative_path: str, content: str) -> int:
    """Archive the current live file (if any) keyed by its version, write `content` to the live
    path with frontmatter `version` set to prior+1 (a new file starts at 1), and return the new
    version. `relative_path` must be a workflow-relative POSIX path under rules/ or skills/;
    anything else raises AcceptError. The caller holds the per-workflow lock."""
```

- Reuse the existing `_valid_staged_path`, `_read_version`, `_set_version` helpers and the exact
  archive-naming (`{stem}.v{old_version}{suffix}` under `workflow_dir/archive/...`).
- Raise `AcceptError` when `_valid_staged_path(relative_path)` is false (covers traversal, backslash,
  colon, absolute, fewer-than-two-parts, and first-part-not-in-{rules,skills}).
- Refactor the per-file body of `accept_learning`'s apply loop to call `apply_instruction_edit`.
  KEEP the existing pre-checks that run BEFORE any file is moved: the staging/workflow disjointness
  check and the loop that validates ALL staged paths first (fail-closed). Do not weaken them.
- `apply_instruction_edit` writes with `encoding="utf-8", newline="\n"` (as accept does today).

### 2. `app/api/learning.py` — two endpoints
Add response/request models and two routes on the existing `router` (prefix `/api`). Use the
existing `_entry(request, workflow_id)` (404s on unknown/unsafe id) and `_workflow_lock(workflow_id)`.

```python
class InstructionFileOut(BaseModel):
    path: str
    content: str

class InstructionsOut(BaseModel):
    instructions: list[InstructionFileOut]

class SaveInstructionIn(BaseModel):
    path: str
    content: str

class SaveInstructionOut(BaseModel):
    path: str
    version: int
```

**`GET /api/learning/{workflow_id}/instructions` -> `InstructionsOut`**
- `entry = _entry(request, workflow_id)`.
- List `entry.path/rules/*.md` then `entry.path/skills/*.md`, each sorted by name; rules before
  skills. For each, return `InstructionFileOut(path=f"{sub}/{name}", content=<utf-8 text>)` where
  `sub` is `"rules"` or `"skills"`. Path is workflow-relative POSIX.
- Skip a directory that does not exist. Guard against symlink escape the same way
  `app/api/runs.py:list_run_files` does: resolve each file and skip it unless
  `resolved.is_relative_to(entry.path.resolve())`. Skip files that fail to read
  (`except (OSError, UnicodeError): continue`).

**`PUT /api/learning/{workflow_id}/instructions` with `SaveInstructionIn` -> `SaveInstructionOut`**
- `entry = _entry(request, workflow_id)`.
- Reject the path with `HTTPException(400)` unless it is a valid rules/|skills/ path AND ends with
  `.md`. You may import/reuse `_valid_staged_path` from `app.learning.accept` for the rules/|skills/
  + traversal check, and add an explicit `.md` suffix check. (A 404 is also acceptable per the
  contract, but prefer 400 for a malformed path.)
- Under `_workflow_lock(workflow_id)`:
  - Compute the live path `live = entry.path.joinpath(*PurePosixPath(path).parts)`. Defence in
    depth: `HTTPException(404)` unless `live.resolve().is_relative_to(entry.path.resolve())`.
  - `HTTPException(404)` if `not live.is_file()` (the editor only saves files the user opened; no
    create in this increment).
  - `version = apply_instruction_edit(entry.path, path, content)`.
  - Return `SaveInstructionOut(path=path, version=version)`.

## Constraints / do-nots
- Touch ONLY `app/learning/accept.py` and `app/api/learning.py`. Do NOT edit any test or other file.
- Do NOT change `accept_learning`'s observable behaviour — the accept tests must stay green.
- No new dependencies. Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.
- The save path must NEVER write outside `workflow_dir/rules/`, `workflow_dir/skills/`, or
  `workflow_dir/archive/`.

## Review B follow-up (SECOND delegation — apply these two fixes to `apply_instruction_edit`)
Your first implementation passed diff-review and security-review. The cross-family reviewer found
two real robustness gaps in `apply_instruction_edit` (both also protect the existing accept path):

1. **Normalize line endings before versioning** (pinned by the new frozen test
   `test_apply_edit_normalizes_crlf_line_endings`). The editor's content comes from a browser
   textarea and on Windows carries CRLF. `_set_version`'s frontmatter regex is LF-only, so a CRLF
   body gets a SECOND frontmatter block prepended with a stale version line. In
   `apply_instruction_edit`, normalize the incoming `content` — replace `\r\n` and lone `\r` with
   `\n` — BEFORE calling `_set_version`. (Do this inside `apply_instruction_edit` so accept benefits
   too.) The saved file must have exactly one frontmatter block and LF endings.

2. **Resolved-containment guard on the write targets** (defence in depth; no new test — mirrors the
   symlink guard in `app/api/runs.py:list_run_files`). Inside `apply_instruction_edit`, compute
   `root = workflow_dir.resolve()`. Before archiving, if the live file exists and
   `not live.resolve().is_relative_to(root)`, raise `AcceptError`. After `archive.parent.mkdir(...)`,
   if `not archive.parent.resolve().is_relative_to(root)`, raise `AcceptError` (this catches a
   symlinked `archive/` or `rules/`/`skills/` directory that would otherwise let `shutil.move`
   escape the workflow tree). These raises must occur before any `shutil.move`/write for the file in
   question. The existing accept/edit tests use no symlinks, so they stay green.

Keep everything else from the first implementation. Do NOT introduce atomic-write / temp-file
rename (that is tracked separately as hardening) and do NOT add run-coordination locking here.

## Scope
- `app/learning/accept.py`
- `app/api/learning.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_edit.py tests/api/test_learning_edit_api.py -q` → all pass.
- `-m pytest tests/core/test_learning_accept.py tests/api/test_learning_api.py -q` → still green.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
