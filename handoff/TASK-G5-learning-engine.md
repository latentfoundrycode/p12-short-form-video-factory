# TASK G-5 — the SkillOpt-derived learning ENGINE (§5.11), optimiser injected/mocked

## Goal (one sentence)
Create `app/learning/engine.py::run_learning` — gather a workflow's quality answers, load its
`criteria/`+`rules/`+`skills/`, hand them to an INJECTED `optimize` callable, and stage the proposed
bounded edits (confined to `rules/`+`skills/`) to a staging area, discarding everything and raising on
any error. NO real LLM / OpenRouter / spend in this increment — `optimize` is injected (the real
OpenRouter optimiser + a separate learning budget + the attended first run are a later increment).

## Governing spec (verbatim — Architecture §5.11)
> For a chosen workflow: gather every `video.json` containing quality answers since the last learning
> run, load that workflow's criteria files together with its current rules and skills, and run the
> SkillOpt-derived optimiser to propose bounded edits.
>
> **Only files inside `workflows/<id>/rules/` and `workflows/<id>/skills/` may be modified. Any
> proposal touching a path outside that is rejected outright.** … The library is unreachable too …
> may be *read* as evidence … but never written. **Proposals are written to a staging area and never
> applied directly.** … On any error, the staging area is discarded and the learning run returns
> entirely to its state before it began, with nothing modified.

Owner decision (2026-09-14, memory `learning-run-spend-policy`): build mocked first; last_learned is
null for now so "since the last learning run" means all quality answers.

## Frozen contract (already committed — do NOT edit)
`tests/core/test_learning_engine.py`.

## What to implement

### `app/learning/__init__.py` (new)
Empty package marker (the dir currently holds only `.gitkeep`).

### `app/learning/engine.py` (new)
```python
from __future__ import annotations
# stdlib: dataclasses, shutil, pathlib.PurePosixPath, Path; typing Callable, Any
from app.core.records import read_request, read_video   # reuse the existing scan/read
```
Define:
- `class LearningError(Exception)` — raised on any failure (wraps the cause).
- `@dataclass(frozen=True) ProposedEdit: path: str; content: str` — `path` is workflow-relative,
  POSIX, and must live under `rules/` or `skills/`.
- `@dataclass(frozen=True) LearningInput: workflow_id: str; labels: list[dict[str, Any]];
  criteria: dict[str, str]; rules: dict[str, str]; skills: dict[str, str]`.
- `@dataclass(frozen=True) LearningResult: staged: list[ProposedEdit]`.
- `type OptimizeFn = Callable[[LearningInput], list[ProposedEdit]]`.

`run_learning(workflow_dir: Path, *, runs_dir: Path, staging_dir: Path, optimize: OptimizeFn) ->
LearningResult`:
1. `workflow_id = workflow_dir.name`.
2. **Gather labels** — scan `runs_dir / workflow_id`'s run dirs (each with a `request.json`); for each
   child dir containing `video.json`, `read_video(child)`, and when `record.quality` is a dict whose
   `answers` is a non-empty dict, append a label dict:
   `{"run_id": run_dir.name, "video_index": record.index, "answers": <answers>,
   "rankings": <quality.get("rankings") or {}>, "accepted": <quality.get("accepted")>}`. Missing runs
   dir → `[]`. Be robust: skip unreadable video.json (swallow `OSError`/`ValueError`/`TypeError`),
   mirror the scan in `app/api/learning.py` / `app/core/statistics.py`.
3. **Load instructions** — for each of `criteria`, `rules`, `skills`: read every top-level `*.md` file
   in `workflow_dir / <name>` into `{filename: text}` (empty dict if the dir is absent).
4. Build `LearningInput` and call `edits = optimize(inp)`.
5. **Validate ALL edits before writing ANY** (whole-batch reject): for each `edit`, treat `edit.path`
   as `PurePosixPath`; it is valid ONLY if it is not absolute, contains no `..` segment, has at least
   two parts, and `parts[0] in {"rules", "skills"}`. If ANY edit is invalid → raise `LearningError`
   (having written nothing).
6. **Stage** — create `staging_dir` fresh; for each edit write `staging_dir / edit.path` (create
   parent dirs, UTF-8, `\n` newline). NEVER write anywhere under `workflow_dir`.
7. Return `LearningResult(staged=list(edits))`.
8. **Revert-on-error** — wrap the whole of steps 2-7 so that on ANY exception (from `optimize`,
   validation, or IO) you `shutil.rmtree(staging_dir, ignore_errors=True)` (discard the staging area)
   and then raise `LearningError` (chain the original with `raise ... from exc`; if the failure was
   your own validation `LearningError`, just re-raise after the cleanup). The live `workflow_dir` is
   never modified in any path.

## Constraints / do-nots
- Touch ONLY `app/learning/__init__.py` (new) and `app/learning/engine.py` (new). Do NOT edit any
  test, `app/api/learning.py`, records, or anything else. No real LLM/OpenRouter call, no network, no
  budget wiring (later increment). No dependency beyond stdlib + `app.core.records`.
- Never write under `workflow_dir` — proposals go ONLY to `staging_dir`.
- Keep `ruff check`, `ruff format --check`, `mypy --strict` (`mypy sdk app`) clean; wrap ≤100 cols.

## Scope
- `app/learning/__init__.py`
- `app/learning/engine.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_engine.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
