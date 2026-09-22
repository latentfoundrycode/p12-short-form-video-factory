# TASK — web-image-sourcing inc6 FIX round 3: redact the query-param api_key from errors

## Why this round
Cross-family review demonstrated a reachable **P1 credential leak**. SerpApi's `SERPAPI_API_KEY`
is a **query-param** secret (the adapter's `_Anon` auth sends **no** auth header). `_http.request()`
redacts only auth-**header** values, so for a non-401/403 status (400, 429-after-retries, 5xx) it
builds the error detail from `response.text` with **no** scrubbing of the query secret. A body that
reflects the key therefore leaks it into `AdapterError` and any log. Confirmed:
`serpapi GET /search failed (400): {"error":"invalid api_key=serpapi-fake-key-not-real"}`.
(The 401/403 path is safe — it uses a fixed string and discards the body.)

A frozen RED contract is already committed (HEAD):
- `tests/sdk/test_http_auth_scrub.py::test_request_redacts_extra_query_param_secrets_from_a_non_auth_error_body`
- `tests/integration/test_media_web_web.py::test_web_search_does_not_leak_the_key_in_a_non_auth_error_body`

## Changes (exactly two files)

### 1. `sdk/sfvf/providers/_http.py` — let callers pass extra secret values to redact
- `_redact(text, auth_headers)` → add an optional third parameter for extra secret strings and scrub
  them alongside the auth-header values:
```python
def _redact(text: str, auth_headers: dict[str, str], extra: Iterable[str] = ()) -> str:
    """... existing docstring ... Also removes each value in `extra` (e.g. a query-param secret the
    auth object does not carry as a header)."""
    secrets: set[str] = set()
    for value in auth_headers.values():
        if value:
            secrets.add(value)
            if " " in value:
                secrets.add(value.split(" ", 1)[1])
    for value in extra:            # NEW
        if value:                  # NEW
            secrets.add(value)     # NEW
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text
```
  (Add `from collections.abc import Iterable` to the imports if not present.)
- `request(...)` → add a keyword-only `redact: Iterable[str] = ()` parameter and pass it through in
  the non-auth branch:
```python
        else:
            detail = _truncate(_redact(response.text, auth_headers, redact))
```
  The 401 → "authentication failed" and 403 → "authorization failed" fixed strings stay unchanged
  (they never read the body). The default `()` keeps every existing caller byte-for-byte identical.

### 2. `sdk/sfvf/providers/serpapi.py` — pass the api_key to the redactor
The adapter already holds `key`. Pass it to `request()` so a reflected key is scrubbed:
```python
                resp = request(
                    client, "GET", url, provider="serpapi", auth=_Anon(), limiter=LIMITER,
                    redact=[key],
                )
```
Nothing else in `serpapi.py` changes (the reserve/billed-flag/reconcile logic and mapping stay
exactly as they are).

## Scope — do NOT touch anything else
Only `sdk/sfvf/providers/_http.py` and `sdk/sfvf/providers/serpapi.py`. Do not change other adapters,
`_auth.py`, `base.py`, `web.py`, `_budget.py`, `context.py`, the registry, or any test. No new
dependencies. Never read/log/print the key beyond passing it into `redact=`.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_http_auth_scrub.py tests/integration/test_media_web_web.py -q` → all pass (the 2 previously-RED tests now green; the existing scrub/web tests stay green).
- Run the whole adapter/provider surface to prove the shared `_http` change regresses nothing:
  `PYTHONPATH=sdk python -m pytest tests/sdk tests/integration/test_image_openai.py tests/integration/test_image_bfl.py tests/integration/test_video_byteplus.py tests/integration/test_video_minimax.py tests/integration/test_video_veo.py tests/integration/test_google_errors.py tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py -q` → all pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean.
