# TASK B-4a — `ctx.secret(name)` accessor (SDK-side secrets read, §5.6)

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`, `docs/`,
or `handoff/`. The reviewer contract `tests/sdk/test_secret.py` is FROZEN — make it pass by changing product
code, not the test.

This is the first, small piece of the OpenRouter provider work: the accessor its adapter will pull the bearer
token through. **Scope is only the read accessor.** The encrypted secret store, the passphrase prompt, and the
injection of a real key into `context.json` (§5.6 app-layer) are explicitly OUT OF SCOPE — they are the
live-key boundary and are not built here.

## Add `secret` to the `Context` class

In `sdk/sfvf/context.py`, add a method to the `Context` class (the one that already has
`emit`/`log`/`stage`/`heartbeat`/`decision`/`step`/`map`):

```python
def secret(self, name: str) -> str:
    ...
```

- Read from the ambient context file's `secrets` dict — `self._file.secrets` (the `ContextFile.secrets`
  field, `dict[str, Any]`, already present). Note the field may be stored on the instance under whatever
  attribute the constructor uses; use the existing pattern (`__init__` stores `file` — see how `workflow_id`
  etc. are wired). If the constructor keeps the `ContextFile` around, read `secrets` from it; if not, capture
  what you need in `__init__` consistently with the other accessors.
- **Present:** return the value as a `str` (`return str(self._file.secrets[name])`), so a permitted key comes
  back verbatim.
- **Absent:** raise `KeyError(name)` — i.e. name the missing key. **The error must name only the key, never a
  value, and must never include any *other* secret's value** (the frozen test asserts no other value leaks).
- **Never log or print the value.** Do not add logging, `emit`, `repr`, or f-strings that interpolate the
  secret value anywhere. Redaction across records/logs is §5.6 app-layer and out of scope; this accessor's job
  is simply to hand the value back without exposing it. A short docstring should say the value is never logged
  and the encrypted store is out of scope.
- Type: `-> str`, mypy-strict clean. Do not add dependencies. Touch only `sdk/sfvf/context.py`.

## Acceptance

- `tests/sdk/test_secret.py` passes (3 tests): permitted value returned verbatim; missing key raises
  `KeyError`; a missing-key error does not leak another secret's value.
- Everything else in the suite still passes; no other behaviour changes.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
