# TASK G-5 fix — close the Windows path-traversal escape in the learning engine (security-auditor BLOCKING)

## Why (confirmed by ground truth on the win32 target)
`_validate_edits` parses `edit.path` with `PurePosixPath` (where `\` and `:` are ORDINARY chars), but
the staging write `staging_dir.joinpath(*PurePosixPath(edit.path).parts)` joins onto a native
`WindowsPath`, which treats `\` as a separator and honours a drive letter. So these pass validation
yet ESCAPE the staging area (verified with `.resolve()`):
- `rules/..\..\evil.md`  → `C:\evil.md`
- `rules/C:\Windows\evil.md` → `C:\Windows\evil.md` (arbitrary absolute)
This breaks §5.11's core invariant (edits confined to rules/skills; live workflow/library/globals
untouched). Committed locking tests are RED:
`tests/core/test_learning_engine.py::test_rejects_backslash_traversal_escape` and
`::test_rejects_backslash_and_drive_letter_paths`.

## Scope
- `app/learning/engine.py`

## Exact change (two defences, both required)
1. In `_validate_edits`, at the TOP of the per-edit loop (before the existing part checks), reject any
   path string containing a backslash or a colon — these never appear in a legitimate POSIX-relative
   `rules/`|`skills/` path and are the Windows escape vectors:
   ```python
   if "\\" in edit.path or ":" in edit.path:
       raise LearningError(f"edit path is outside rules/ and skills/: {edit.path}")
   ```
   Keep the existing checks (absolute, `..` segment, `< 2` parts, `parts[0] in {rules, skills}`).
2. Defence-in-depth at the write site: after computing `destination`, verify it stays within staging
   using the SAME (native) path semantics as the write, BEFORE creating parents / writing:
   ```python
   destination = staging_dir.joinpath(*PurePosixPath(edit.path).parts)
   if not destination.resolve().is_relative_to(staging_dir.resolve()):
       raise LearningError(f"edit path escapes the staging area: {edit.path}")
   destination.parent.mkdir(parents=True, exist_ok=True)
   destination.write_text(edit.content, encoding="utf-8", newline="\n")
   ```
   (This runs inside the existing try, so the `except` still rmtree's staging on failure. Because the
   containment check precedes the write, and full validation precedes the staging loop, nothing
   escapes and nothing partial survives.)

Change nothing else. Do NOT edit any test.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_engine.py -q` → ALL pass (incl. the two escape tests).
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
