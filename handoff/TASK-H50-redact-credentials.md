# TASK-H50 — redact the submitted credential from non-auth error bodies

A frozen RED contract fails: `tests/sdk/test_http_auth_scrub.py::test_request_redacts_the_submitted_credential_from_a_non_auth_error_body`. The 401/403 fixed-string scrub does not cover other statuses, so a provider that reflects the `Authorization` header (or any header we sent) on a 400/5xx leaks the submitted credential into `AdapterError.detail`. Fix: redact the exact credentials we sent from the non-2xx body, precisely (no heuristic), while keeping the rest of the body for diagnostics.

## The fix — `sdk/sfvf/providers/_http.py`

1. Capture the auth headers once so they can be reused for redaction. Change the existing
   `merged.update(auth.headers())` (near the top of `request()`) to:
   ```python
   auth_headers = auth.headers()
   merged.update(auth_headers)
   ```

2. Add a module-level helper:
   ```python
   def _redact(text: str, auth_headers: dict[str, str]) -> str:
       """Remove the credentials we sent (each auth header value, and the token after a scheme
       prefix like 'Bearer'/'Basic') from an error body, so a reflected credential can't land in
       the detail. Precise — only the exact strings we transmitted are removed."""
       secrets: set[str] = set()
       for value in auth_headers.values():
           if value:
               secrets.add(value)
               if " " in value:
                   secrets.add(value.split(" ", 1)[1])  # token after a scheme (Bearer/Basic)
       for secret in secrets:
           text = text.replace(secret, "[redacted]")
       return text
   ```

3. In the non-2xx error path, apply it to the ELSE branch only (the 401/403 fixed strings stay as
   they are). Change:
   ```python
       else:
           detail = _truncate(response.text)
   ```
   to:
   ```python
       else:
           detail = _truncate(_redact(response.text, auth_headers))
   ```
   (Redact BEFORE truncating so a credential near the 200-char boundary is fully removed.)

Nothing else changes: the 401/403 branches, the 429-retry, the success path, and `parse_json` /
`download_bytes` are untouched.

## Scope (ONLY this file)
- `sdk/sfvf/providers/_http.py`
Do NOT touch any test, other file, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency. Minimal change.
- `ruff check`, `ruff format --check`, and `mypy` clean on the file.

## Acceptance criteria
1. `python -m pytest tests/sdk/test_http_auth_scrub.py` — all pass (the new redact test plus the
   existing 401/403 fixed-string and 503-preservation tests).
2. `python -m pytest tests/sdk/test_providers_kit.py` — the kit hygiene contract still passes.
3. `ruff check` + `ruff format --check` + `mypy` clean on `sdk/sfvf/providers/_http.py`.
4. git diff shows exactly that one file changed.
