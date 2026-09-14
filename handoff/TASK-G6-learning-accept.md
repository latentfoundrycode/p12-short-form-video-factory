# TASK G-6 — accept / reject staged learning proposals (§5.11)

## Goal (one sentence)
Add `app/learning/accept.py` with `accept_learning` (apply a staged proposal set to the live
workflow: archive the prior file, bump its frontmatter `version`, write the accepted content) and
`reject_learning` (discard the staging area) — the acceptance half of §5.11. No LLM/network/spend.

## Governing spec (verbatim — Architecture §5.11)
> Proposals are written to a staging area and never applied directly. The live files are untouched
> until the user accepts.
>
> **Acceptance archives the previous version. The prior file moves to `archive/` and the version
> number in its frontmatter increments**, so that the record of which instructions produced which
> past video stays accurate.

The learning module is the single sanctioned exception to "never write into `workflows/` while
running" (§ decisions), and even then it only ever writes `rules/`, `skills/`, and `archive/`.

## Frozen contract (already committed — do NOT edit)
`tests/core/test_learning_accept.py`.

## What to implement — `app/learning/accept.py` (new)
```python
from __future__ import annotations
import re, shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
```
Define:
- `class AcceptError(Exception)`.
- `@dataclass(frozen=True) class AcceptResult: applied: list[str]` (workflow-relative POSIX paths).

Frontmatter version helpers (a rule/skill file may begin with a `---\n … \n---\n` frontmatter block
containing a `version: <int>` line, per SDK §8.1):
- `_read_version(text: str) -> int` — if `text` starts with a `---` frontmatter block, find a line
  matching `^version:\s*(\d+)\s*$` inside it and return that int; otherwise return `1` (no block or
  no version line ⇒ treat as version 1).
- `_set_version(text: str, version: int) -> str` — return `text` with its frontmatter `version` line
  set to `version`. If a frontmatter block exists and has a version line, replace it; if the block
  exists without one, insert `version: {version}` as the first line inside the block; if there is no
  block, prepend `---\nversion: {version}\n---\n`.

Path guard (reuse the engine's rule): a staged relative path is valid only if, as a `PurePosixPath`,
it is not absolute, has no `..` segment, has ≥2 parts, `parts[0] in {"rules","skills"}`, and the raw
string contains no backslash or colon. (Import from `app.learning.engine` if a helper is exposed, or
mirror it — a small duplication is fine.)

`accept_learning(workflow_dir: Path, staging_dir: Path) -> AcceptResult`:
1. Collect every file under `staging_dir` (`staging_dir.rglob("*")`, files only) as a workflow-
   relative POSIX path (relative to `staging_dir`).
2. **Validate ALL collected paths first** (the path guard above). If ANY is invalid → raise
   `AcceptError`, applying nothing (no archive, no live write). (Defence in depth — the G-5 engine
   already confines staged paths, but accept must not trust that blindly.)
3. For each staged relpath (sorted):
   - `live = workflow_dir / relpath`.
   - If `live.is_file()`: `old = _read_version(live.read_text("utf-8"))`; move it to
     `workflow_dir / "archive" / <relpath-with-".v{old}"-inserted-before-the-suffix>` (create parent
     dirs; e.g. `rules/tone.md` at v3 → `archive/rules/tone.v3.md`). `new = old + 1`.
   - Else: `new = 1` (nothing to archive).
   - `content = _set_version(<staged file text>, new)`; write it to `live` (create parent dirs,
     UTF-8, `\n` newlines).
4. `shutil.rmtree(staging_dir, ignore_errors=True)` (the accepted proposals are consumed).
5. Return `AcceptResult(applied=<sorted relpaths>)`.

`reject_learning(staging_dir: Path) -> None`: `shutil.rmtree(staging_dir, ignore_errors=True)` — the
live workflow is never touched.

## Constraints / do-nots
- Touch ONLY `app/learning/accept.py` (new). Do NOT edit any test, `app/learning/engine.py`, the API,
  or anything else. No LLM/network/budget. Stdlib only (`re`, `shutil`, `pathlib`, `dataclasses`).
- `accept_learning` writes ONLY under `workflow_dir/rules`, `workflow_dir/skills`, and
  `workflow_dir/archive` — never elsewhere.
- Keep `ruff check` / `ruff format --check` / `mypy --strict` (`mypy sdk app`) clean; ≤100 cols.

## Scope
- `app/learning/accept.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_accept.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
