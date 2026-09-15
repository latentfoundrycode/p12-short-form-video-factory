# TASK — loop-closing fixes: instructions in the step cache key + skip unreadable files

Cross-family review found two real gaps in the loop-closing change. Two new frozen tests now fail:
- `tests/sdk/test_step_instructions_cache.py` (P1a — instructions must be part of the step cache key)
- `tests/integration/test_agents_instructions.py::test_unreadable_instruction_file_is_skipped_not_crashing`
  (P2b — a non-UTF-8 instruction file must be skipped, not crash the call)

Fix ONLY these two files: `sdk/sfvf/context.py` and `sdk/sfvf/agents.py`.

## P1a — a workflow's instructions must be part of every step's cache key
Today `ctx.step(family, inputs=...)` keys on `step_key(workflow_version, family, inputs)`; the injected
instructions aren't in the key, so a step cached before a rule changed is re-served on the next run —
the accepted rule never takes effect on a same-input rerun.

In `sdk/sfvf/context.py`:
- Add a small helper (module function) that reads the instruction files' text safely:
  ```python
  def _read_instruction_text(paths: list[Path]) -> str:
      parts: list[str] = []
      for path in paths:
          try:
              text = Path(path).read_text(encoding="utf-8").strip()
          except (OSError, UnicodeError):   # missing / unreadable / non-utf-8 → skip, never crash
              continue
          if text:
              parts.append(text)
      return "\n\n".join(parts)
  ```
- Give `Context` a cached digest of its instructions, computed once (e.g. in `__init__` after
  `self.instructions = file.instructions`, store `self._instructions_digest`):
  `hashlib.sha256(_read_instruction_text(self.instructions).encode("utf-8")).hexdigest()` when the
  text is non-empty, else `""`. (Import `hashlib`.)
- Where the step's cache key is built (the `_Step` handle — it calls `step_key(ctx.workflow_version,
  family, inputs)` on enter), fold the digest into the inputs ONLY when it is non-empty:
  `key_inputs = {**inputs, "__sfvf_instructions__": ctx._instructions_digest} if
  ctx._instructions_digest else inputs`, then `step_key(..., key_inputs)`.
  Do NOT change `step_key` itself, and do NOT change the `inputs` recorded in events / used by the
  body — only the value passed to `step_key`. When there are no instructions the digest is `""`, so
  the key is byte-identical to today (existing caches stay valid).
  (`ctx.map` builds per-item steps through the same `_Step`/key path — make sure the fold is at that
  shared point so map steps get it too; do not duplicate the logic in two places.)

## P2b — agents must skip an undecodable instruction file
In `sdk/sfvf/agents.py`, `_instruction_text` currently catches only `OSError`. Widen it to also catch
`UnicodeError` (which covers `UnicodeDecodeError`), so a non-UTF-8 `.md` is skipped rather than
raising and breaking every LLM call:
```python
except (OSError, UnicodeError):
    continue
```
Nothing else in `agents.py` changes.

## Constraints / do-nots
- Touch ONLY `sdk/sfvf/context.py` and `sdk/sfvf/agents.py`. Do NOT edit any test or other file.
- Keep the digest computed once per Context (not per step file-read loop); the fold into the key must
  be a true no-op when there are no instructions (existing step/cache tests must stay byte-identical).
- Keep `ruff check .`, `ruff format --check .`, and `mypy` clean; ≤100 cols.

## Scope
- `sdk/sfvf/context.py`
- `sdk/sfvf/agents.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_step_instructions_cache.py tests/integration/test_agents_instructions.py -q` → all pass.
- `-m pytest -q` (full) → green (existing step/cache/agents tests must still pass).
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
