# TASK S2c — redact secret values from the event stream (§5.6 defense-in-depth)

**Builder:** Cursor. **Product code only** in `app/core/supervisor.py`. Do NOT touch `tests/`, `docs/`,
`handoff/`. The reviewer contract `tests/core/test_secret_redaction.py` is FROZEN.

The §5.6 secret path is otherwise closed (store → allowlist injection → passphrase not in child env →
context.json not downloadable/scrubbed). This adds the last defense-in-depth layer: if a workflow subprocess
ever emits one of its injected secret VALUES to stdout (or a log/error), it must not be persisted verbatim in
`events.jsonl` / the SSE feed. Every run event flows through `_RunState.record_event`, so redact there.

## Implement in `app/core/supervisor.py`

1. Add a module-level redactor:
```python
def _redact_secrets(obj: _T, values: frozenset[str]) -> _T:
    """Return obj with every occurrence of each secret value replaced by '[REDACTED]', walking
    nested dicts/lists/strings. Non-strings are returned unchanged. Empty values are ignored."""
    real = [v for v in values if v]
    if not real:
        return obj
    def scrub(node: Any) -> Any:
        if isinstance(node, str):
            out = node
            for v in real:
                out = out.replace(v, "[REDACTED]")
            return out
        if isinstance(node, dict):
            return {k: scrub(x) for k, x in node.items()}
        if isinstance(node, list):
            return [scrub(x) for x in node]
        return node
    return scrub(obj)  # type: ignore[return-value]
```
(Use a `TypeVar`/PEP 695 `[_T]` so it's typed generically; the return-type-ignore or a cast is fine for the
recursive `scrub`. Keep mypy-strict happy.)

2. Add a field to the `_RunState` dataclass:
```python
    secret_values: frozenset[str] = frozenset()
```

3. In `record_event`, redact before writing:
```python
    def record_event(self, run_dir: Path, event: dict[str, Any], source: str) -> None:
        with self.lock:
            append_event(run_dir, _redact_secrets(event, self.secret_values), source=source)
```

4. Where `run_request` builds the `_RunState(...)` (≈ line 324), populate it from the run's injected secrets —
   the same allowlisted mapping S2a computes (`injected`). Pass
   `secret_values=frozenset(v for v in injected.values() if v)` so only the actual injected values (non-empty)
   are redacted. (If the state is built before `injected` is computed, move the computation up or set the field
   right after — keep the injection behaviour unchanged.)

Never log a secret value. mypy-strict clean. No new dependency. Touch only `app/core/supervisor.py`.

## Acceptance

`tests/core/test_secret_redaction.py` passes (5 tests): `_redact_secrets` scrubs every nested occurrence and
leaves non-strings/non-secrets alone; empty `values` is identity; `record_event` with configured
`secret_values` writes `[REDACTED]` (not the value) to `events.jsonl`; with none it's verbatim; an empty-string
secret value is ignored (never "matches"). The existing `tests/api/test_runs.py`, `test_secret_injection.py`,
`test_secret_exposure.py`, `test_supervisor.py`, and the rest of the suite still pass.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/core/test_secret_redaction.py tests/api/test_runs.py tests/core/test_supervisor.py
```
(The full `pytest` run also shows 3 pre-existing `finalize`/`example_workflow` failures — ONLY the HyperFrames
toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
