# TASK-H51 — BFL: refuse a polling_url not on an https *.bfl.ai host

A frozen RED contract fails: `tests/integration/test_provider_live_fixes.py::test_bfl_refuses_a_polling_url_not_on_an_https_bfl_host` (two parametrized cases). `request()` merges the `x-key: BFL_API_KEY` header onto every request, including the poll to the `polling_url` returned in BFL's submit response. A spoofed or MITM'd submit response could name a foreign host or a plaintext `http` URL and harvest the key. The adapter must validate the `polling_url` BEFORE polling and refuse anything that is not `https` on a `*.bfl.ai` host.

## The fix — `sdk/sfvf/providers/bfl.py`

In `_submit_poll_download`, after reading `polling_url` from the submit response and the existing empty-check, validate the host/scheme before calling `poll_until`. Add a small module-level helper and call it:

```python
from urllib.parse import urlsplit   # add to the imports

def _require_bfl_host(url: str) -> None:
    """Refuse a polling_url that is not https on a BFL-designated host, so the x-key never leaves
    *.bfl.ai over https (defends against a spoofed/MITM'd submit response)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not (host == "bfl.ai" or host.endswith(".bfl.ai")):
        raise AdapterError("bfl", where="submit", detail="polling_url is not an https bfl.ai host")
```

Call site (right after the `if not polling_url: raise ...` guard, before building `_done`/`poll_until`):

```python
    polling_url = submit_json.get("polling_url")
    if not polling_url:
        raise AdapterError("bfl", where="submit", detail="no polling_url in submit response")
    _require_bfl_host(polling_url)
```

Nothing else changes. A legitimate regional URL like `https://api.us1.bfl.ai/v1/get_result?id=...` passes (host ends with `.bfl.ai`, scheme https), so the existing behaviour and the `test_bfl_polls_the_regional_polling_url` contract are unaffected.

## Scope (ONLY this file)
- `sdk/sfvf/providers/bfl.py`
Do NOT touch any test, other file, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency (`urllib.parse` is stdlib). Minimal change.
- `ruff check`, `ruff format --check`, and `mypy` clean on the file.

## Acceptance criteria
1. `python -m pytest tests/integration/test_provider_live_fixes.py` — all pass (the two new H51 cases now raise AdapterError before any GET to the bad host; the regional-polling_url test still passes).
2. `python -m pytest tests/integration/test_image_bfl.py` — the frozen P-6 contract still passes (its mock polling_url is `https://api.bfl.ai/...`, which is allowed).
3. `ruff check` + `ruff format --check` + `mypy` clean on `sdk/sfvf/providers/bfl.py`.
4. git diff shows exactly that one file changed.
