# TASK G-6 fixes — two review defects in `app/learning/accept.py`

The decorrelated review of `app/learning/accept.py` found two real defects. Two new regression
tests were added to the frozen contract `tests/core/test_learning_accept.py` and currently FAIL.
Fix **only** `app/learning/accept.py` so all 7 tests pass. Do NOT edit the tests or any other file.

## Fix 1 — `_set_version` corrupts the frontmatter (glues the closing fence)
`_VERSION = re.compile(r"^version:\s*(\d+)\s*$", re.MULTILINE)`. The trailing `\s*` is greedy and
`\s` includes `\n`, so when the `version:` line is the last line of the frontmatter body (the normal
case), the match swallows the newline after the digits. `_set_version`'s replace branch then splices
across that swallowed newline and deletes it:

- live `---\nversion: 3\n---\nBe concrete.` + staged content, bumping to 4, currently produces
  `---\nversion: 4---\nOpen on an object.` — the closing `---` fence is glued onto the version line.
- Result: the live file's frontmatter is no longer a well-formed block; `_read_version` of it returns
  `1`, so the NEXT accept archives it as `v1` and bumps `1→2` instead of continuing the real sequence
  — breaking the §5.11 guarantee that the version increments accurately.

**Fix:** stop the version match from consuming the trailing newline. Change the tail of `_VERSION`
from `\s*$` to `[ \t]*$` (match only spaces/tabs before the line end), or equivalently restrict the
replaced span in `_set_version` to the digits alone. The insert-path (frontmatter without a version
line) and the no-frontmatter path are already correct — touch only the replace-existing branch /
the regex. After the fix, bumping 3→4 must yield `---\nversion: 4\n---\nOpen on an object.` and
`_read_version` of the written file must return `4`.

## Fix 2 — no guard against `staging_dir` overlapping `workflow_dir` (data loss)
`accept_learning` ends with `shutil.rmtree(staging_dir, ...)`. If `staging_dir` equals `workflow_dir`
or either directory contains the other, that discard deletes the live workflow (and all staged paths
can be individually valid, so the existing per-path guard does not catch it). This mirrors the
disjoint-staging guard already enforced in the G-5 engine (`app/learning/engine.py`).

**Fix:** at the very top of `accept_learning`, before collecting or moving anything, reject an
overlap and raise `AcceptError`. Use resolved paths:
```python
wf = workflow_dir.resolve()
st = staging_dir.resolve()
if wf == st or wf.is_relative_to(st) or st.is_relative_to(wf):
    raise AcceptError(...)
```
Nothing may be moved, written, or removed when this fires.

## Constraints
- Touch ONLY `app/learning/accept.py`. No other files, no test edits. Stdlib only.
- Keep `ruff check .`, `ruff format --check .`, and `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/learning/accept.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_accept.py -q` → 7 passed.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
