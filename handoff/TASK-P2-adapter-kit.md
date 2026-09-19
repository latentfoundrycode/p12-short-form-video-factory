# TASK — P-2: the adapter kit (auth + HTTP + rate-limit hardening)

## Goal (one sentence)
Add the shared provider-adapter kit under `sdk/sfvf/providers/`: `base.py` (`AdapterError`, `Cost`),
`_auth.py` (four auth strategies), `_http.py` (`request` with 429-retry + hygienic errors, `parse_json`),
and an H8 guard in `sdk/sfvf/_ratelimit.py` — so the frozen contract goes green.

## Spec (docs/PROVIDER_LAYER_PLAN.md §3.3) — authoritative
Every adapter shares this kit so auth, retrying HTTP, and error hygiene are written once. Credentials
(a bearer token, an `x-key`, a minted JWT, an SA private key) must NEVER appear in an error message, a log,
or the headers of a request they don't belong to. The generic submit→poll→download loop is NOT part of this
increment (it lands in P-4a with the first async adapter).

## Frozen contract (already committed — do NOT edit)
`tests/sdk/test_providers_kit.py`. Make it pass without changing it; the full suite must stay green.

## Import-weight rule (important)
Keep the kit importable in a lean workflow venv that installed only `sfvf` core. `import sfvf.providers._auth`,
`._http`, `.base` must need **stdlib only** at module top. Anything third-party is lazy-imported inside the
method that uses it (mirror `sdk/sfvf/agents.py` / `media/speech.py`), raising a clear error if absent.

## What to create / change

### 1. `sdk/sfvf/providers/base.py` (new)
```python
class AdapterError(RuntimeError):
    """A provider call failed. The message is HYGIENIC: provider + where + status + a truncated body
    only — never an auth header value, a URL query string, or a full response body."""
    def __init__(self, provider: str, *, status: int | None = None, where: str = "",
                 detail: str = "") -> None:
        self.provider = provider; self.status = status; self.where = where; self.detail = detail
        parts = [f"{provider}"]
        if where: parts.append(where)
        parts.append("failed")
        if status is not None: parts[-1] = f"failed ({status})"
        msg = " ".join(parts)
        if detail: msg += f": {detail[:200]}"
        super().__init__(msg)

@dataclass(frozen=True)
class Cost:
    amount: float
    source: str   # "reported" | "metered" | "priced"
```

### 2. `sdk/sfvf/providers/_auth.py` (new) — stdlib top-level imports only
Common helper: base64url WITHOUT padding, e.g.
`_b64url(raw: bytes) -> str = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()`.

- **`BearerAuth(token)`** → `headers() -> {"Authorization": f"Bearer {token}"}`.
- **`HeaderAuth(name, value)`** → `headers() -> {name: value}`.
- **`JwtMintAuth(access_key, secret_key, *, ttl_s=1800, now=time.time)`** — local HS256, no network:
  - `headers() -> {"Authorization": f"Bearer {self._token()}"}`.
  - `_token()`: reuse the cached token while `now() < cached_exp`; otherwise mint and cache.
  - Mint: header `{"alg":"HS256","typ":"JWT"}`; payload `{"iss": access_key, "exp": int(now())+ttl_s,
    "nbf": int(now())}`. `signing_input = f"{_b64url(header_json)}.{_b64url(payload_json)}"` (compact
    JSON, `separators=(",",":")`, sorted keys is fine). `sig = hmac.new(secret_key.encode(),
    signing_input.encode(), hashlib.sha256).digest()`. `token = f"{signing_input}.{_b64url(sig)}"`;
    `cached_exp = int(now())+ttl_s`. The secret key never appears in the token or any output.
- **`GoogleSaAuth(sa: dict, *, scope="https://www.googleapis.com/auth/cloud-platform", transport=None,
  now=time.time)`** — Agent Platform / Vertex service account. `sa` has `client_email`, `private_key`
  (PEM), `token_uri`:
  - `headers() -> {"Authorization": f"Bearer {self._access_token()}"}`.
  - `_access_token()`: reuse while `now() < cached_exp`; otherwise exchange and cache.
  - Exchange: LAZY-import `cryptography` (`serialization.load_pem_private_key`, sign with
    `padding.PKCS1v15()` + `hashes.SHA256()`) and `httpx2`. Build an RS256 assertion: header
    `{"alg":"RS256","typ":"JWT"}`; payload `{"iss": sa["client_email"], "scope": scope,
    "aud": sa["token_uri"], "iat": int(now()), "exp": int(now())+3600}`; sign the same
    `f"{_b64url(h)}.{_b64url(p)}"` signing input. POST **form-encoded** to `sa["token_uri"]` with
    `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer` and `assertion=<jwt>` (use an
    `httpx2.Client(transport=transport)` so tests can inject a `MockTransport`; `transport=None`
    means a normal client). Parse `{"access_token","expires_in"}`; `cached_exp = now()+expires_in`.
  - On a non-2xx exchange: raise `AdapterError("google", status=<code>, where="token exchange",
    detail="token exchange failed")` — do NOT put the assertion, the private key, or the response body
    that might echo them into the error. The private key must never appear in `headers()` output either.

### 3. `sdk/sfvf/providers/_http.py` (new) — no top-level third-party import
```python
def request(client, method, url, *, provider, auth, limiter, json=None, headers=None,
            max_attempts=4):
    merged = dict(headers or {}); merged.update(auth.headers())
    path = url.split("?", 1)[0]           # drop the query so it never reaches an error message
    where = f"{method} {path}"
    for attempt in range(max_attempts):
        with limiter.slot(provider):
            resp = client.request(method, url, headers=merged, json=json)
        if 200 <= resp.status_code < 300:
            return resp
        if resp.status_code == 429 and attempt < max_attempts - 1:
            limiter.penalize(provider, _retry_after_s(resp.headers.get("Retry-After")))
            continue
        raise AdapterError(provider, status=resp.status_code, where=where,
                           detail=_truncate(resp.text))
    raise AdapterError(provider, status=429, where=where, detail="rate limited after retries")

def parse_json(resp, *, provider, where):
    try:
        data = resp.json()
    except Exception as exc:                # noqa: BLE001 — any decode failure is an adapter error
        raise AdapterError(provider, status=resp.status_code, where=where,
                           detail="invalid JSON body") from exc
    if not isinstance(data, dict):
        raise AdapterError(provider, status=resp.status_code, where=where,
                           detail="non-object JSON body")
    return data
```
- `_retry_after_s(value)`: parse to a non-negative float; missing/invalid → `0.0`.
- `_truncate(text)`: the response body cut to ~200 chars. The body may contain provider text but never our
  auth header value (that is in the request, not the response) — the contract checks the query string and
  the bearer token do not appear in the error.
- `client.request(...)` is the passed `httpx2.Client`; `limiter` is a `sfvf._ratelimit.RateLimiter`.

### 4. `sdk/sfvf/_ratelimit.py` — H8 guard (edit the existing file)
`configure(provider, ...)` must REFUSE (raise `RuntimeError`) when a slot for that provider is currently
held — replacing a live `Semaphore` is the H8 bug. Add an active-holder counter to `_ProviderState`
(increment under `state.lock` right after `semaphore.acquire()` in `slot()`, decrement in the `finally`),
and in `configure()` raise `RuntimeError(f"cannot reconfigure provider {provider!r} while in use")` when the
counter is > 0. Configuring before the first slot (counter 0) stays allowed. Do not change any other
behaviour; the existing `tests/sdk/test_ratelimit.py` must stay green.

## Constraints / do-nots
- Create ONLY `sdk/sfvf/providers/base.py`, `_auth.py`, `_http.py`; edit ONLY `sdk/sfvf/_ratelimit.py`.
  Do NOT edit the frozen test or any other file.
- No `app.*` import. No NEW third-party dependency — `cryptography` and `httpx2` already exist in the venv;
  import them lazily so the kit's module import stays stdlib-only.
- Keep `ruff check .`, `ruff format --check .`, `mypy` clean; ≤100 cols.

## Scope
- `sdk/sfvf/providers/base.py`
- `sdk/sfvf/providers/_auth.py`
- `sdk/sfvf/providers/_http.py`
- `sdk/sfvf/_ratelimit.py`

## Verify (from the worktree; set `PYTHONPATH` to the worktree `sdk` so imports resolve here)
- `-m pytest tests/sdk/test_providers_kit.py -q` → all pass.
- `-m pytest tests/sdk/test_ratelimit.py -q` → still green.
- `-m pytest -q` (full) → green apart from the pre-existing HyperFrames/chrome env failures in test_finalize.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
