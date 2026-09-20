# TASK-Ph1-http-auth-scrub: Scrub reflected credentials from auth-failure error details

## Objective
Fix the following confirmed defect — repair the named cause, nothing else.
Root cause (one sentence): in `sdk/sfvf/providers/_http.py`, `request()`'s non-2xx error
path raises `AdapterError` with `detail=_truncate(response.text)` for every status,
so when a provider echoes the *submitted* API key back in a 401/403 response body
(observed live with OpenAI) that credential leaks into the error and any log of it.
A frozen contract test, `tests/sdk/test_http_auth_scrub.py`, currently FAILS and must
pass: on an auth-failure status the reflected key must not reach the error, while the
provider, where, and status must still be named; a 5xx body marker must still survive.
This is a RED→GREEN increment: make the frozen test green by editing exactly one source
file, without regressing the existing hygiene contract.

## Scope
Files you may create or modify:
- `sdk/sfvf/providers/_http.py`

Do not modify anything else.

## Out of scope
- Any test file, including `tests/sdk/test_http_auth_scrub.py` and
  `tests/sdk/test_providers_kit.py` (both are FROZEN — read them, do not edit them).
- Any other file under `sdk/`, and all of `app/`, `frontend/`.
- `docs/` and `handoff/`
- `.cursor/`, CI configuration
- `.env` and anything under secrets/
- Dependencies / lockfiles

## Context
Security surface: this increment is on the input-handling / credential-hygiene boundary
between a provider adapter and an untrusted upstream HTTP response. The trust boundary is
the HTTP response body: it is attacker-or-provider-controlled data that must never be
allowed to carry a submitted credential into an error or a log. Follow
`.cursor/rules/secure-coding.mdc` (already in force). Never reproduce a secret value; refer
to keys by name only.

The reflected-credential problem the frozen test encodes: some providers (OpenAI, live)
put the *submitted* API key into the JSON body of a 401/403. Today the whole body flows
into `AdapterError.detail` via `_truncate(response.text)`.

The function to change, `request()` in `sdk/sfvf/providers/_http.py`, ends its non-2xx
path with exactly this raise (lines ~60-67):

```python
from .base import AdapterError

raise AdapterError(
    provider,
    status=response.status_code,
    where=where,
    detail=_truncate(response.text),
)
```

`_truncate` is the local `text[:200]` helper (lines 21-22). The 429-retry `continue`
(line 56-58), the success path (line 54-55), and the post-loop "rate limited after
retries" raise (lines 69-76) are unrelated and must stay untouched.

`AdapterError` (in `sdk/sfvf/providers/base.py`) builds its message from
`provider`, `where`, and `status` independently of `detail`:

```python
parts = [provider]
if where:
    parts.append(where)
parts.append("failed")
if status is not None:
    parts[-1] = f"failed ({status})"
message = " ".join(parts)
if detail:
    message += f": {detail[:200]}"
```

So provider / where / status survive in the message regardless of what `detail` is —
which is why replacing `detail` with a fixed non-echoing string still satisfies the
"still names provider/where/status" assertions. `.detail` is stored on the exception and
is asserted separately, so the fixed string must itself not contain the echoed key.

The frozen contract, `tests/sdk/test_http_auth_scrub.py`, drives `request()` through an
`httpx2.MockTransport` with an idle `RateLimiter` (no live network) and asserts:
- for `status` in {401, 403}: the echoed key `sk-LEAKED-...` is absent from both
  `str(exc.value)` and `exc.value.detail`, while `"acme"`, `"/generate"`, and the status
  string are present in the message.
- for a 503 with body `text=marker`: `marker` and `"503"` are both present in
  `str(exc.value)` (non-auth bodies stay surfaced).

The existing hygiene contract `tests/sdk/test_providers_kit.py` (incl.
`test_request_raises_a_hygienic_error_on_non_2xx`) must not regress.

## Requirements
1. In `request()`'s non-2xx error path only, when `response.status_code` is `401` or
   `403`, raise `AdapterError` with a **fixed, non-echoing** `detail` string that does
   NOT include `response.text` (e.g. `"authentication failed"` for 401 and
   `"authorization failed"` for 403, or a single fixed phrase — your choice).
2. Preserve `provider`, `status=response.status_code`, and `where` on that raise exactly
   as today.
3. For every other non-2xx status (400, 5xx, ...), keep
   `detail=_truncate(response.text)` unchanged — those bodies are diagnostic and carry no
   submitted credential; do NOT scrub them.
4. Leave the 429-retry path, the success path, and the post-loop "rate limited after
   retries" raise untouched.
5. The change must be the smallest correct edit to the error path — no refactor of the
   surrounding function, no new helper unless genuinely needed.

## Acceptance criteria
- [ ] `python -m pytest tests/sdk/test_http_auth_scrub.py` — all 3 cases pass
      (401 scrub, 403 scrub, 503 body preserved).
- [ ] `python -m pytest tests/sdk/test_providers_kit.py` — still all green; in particular
      `test_request_raises_a_hygienic_error_on_non_2xx` does not regress.
- [ ] `ruff check sdk/sfvf/providers/_http.py` clean.
- [ ] `ruff format --check sdk/sfvf/providers/_http.py` clean.
- [ ] `mypy` clean on `sdk/sfvf/providers/_http.py`.
- [ ] No new Semgrep high findings; the credential-hygiene boundary is enforced so an
      echoed credential in a 401/403 body never reaches `AdapterError` or its message.
- [ ] `git diff --name-only` shows exactly one changed file: `sdk/sfvf/providers/_http.py`.

## Constraints
- Do not add dependencies. Standard library only.
- Do not read or write any file outside this workspace (the folder you were started in).
  Everything you need is inside it; everything you produce goes inside it.
- Do not fix by suppressing the symptom — no broad scrubbing of all error bodies, no
  swallowing the error, no widened status match beyond the auth-failure set {401, 403}.
- Do not edit the reproduction test (`tests/sdk/test_http_auth_scrub.py`) or any other
  test.
- Do not leave any debug print or stray marker.
- Do not refactor code outside the scope, even if it looks wrong.
- Follow existing conventions in the file you touch (the `from .base import AdapterError`
  local-import pattern, `_truncate`, the existing raise shape).
- Prefer reuse over new code and write the minimum that meets the acceptance criteria (the
  frozen `minimal-code.mdc` is in force). This never overrides the security requirement
  above.
- If you believe the real cause is different from the one named, stop, do not change code,
  and report why in your summary — the supervisor will re-diagnose.
- Any console process your code launches on Windows is created windowless
  (`creationflags=subprocess.CREATE_NO_WINDOW` in Python — `0` on other platforms). (Not
  expected for this task.)
- If the brief, the rules, or the tooling got in your way, append one dated line to
  `docs/BUILDER_NOTES.md` describing it. Do not try to fix the tooling.

## Done
Print the list of every file you changed and a one-paragraph summary of what you did.
State in one sentence how the change addresses the named cause (the reflected credential
in a 401/403 body no longer flows into `AdapterError.detail`).
