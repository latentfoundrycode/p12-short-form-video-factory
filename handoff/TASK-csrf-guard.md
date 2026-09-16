# TASK — CSRF guard for state-changing requests (H47)

## Goal (one sentence)
Add one middleware to the app that refuses cross-site state-changing requests (via the browser's
`Sec-Fetch-Site` header), closing the drive-by CSRF exposure on every mutating endpoint at once.

## Why
This is a local single-owner web app with no auth. A page on another website the owner visits can
make their browser POST/PUT/DELETE to `http://localhost:<port>/api/...` with the owner's session
(launch/stop/delete runs, accept learning edits, schedules, …). `Sec-Fetch-Site` is a **forbidden
header** — page JavaScript cannot forge it — so it is a reliable, spoof-proof origin signal.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_csrf.py` (8 tests). All existing tests must stay green.

## What to change

### 1. New module `app/core/csrf.py`
A small ASGI/Starlette HTTP middleware dispatch function:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Reads are not state-changing; OPTIONS is the CORS preflight. Only guard mutating methods.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Values a browser stamps for a request from a DIFFERENT origin. `same-origin`, `none`, and an
# absent header (non-browser clients) are allowed.
_BLOCKED_FETCH_SITES = frozenset({"cross-site", "same-site"})


async def csrf_guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method.upper() not in _SAFE_METHODS:
        site = request.headers.get("sec-fetch-site")
        if site in _BLOCKED_FETCH_SITES:
            return JSONResponse(
                status_code=403,
                content={"detail": "cross-site state-changing request refused"},
            )
    return await call_next(request)
```

### 2. Wire it in `app/main.py`'s `create_app`
Register the middleware on the `application` (both the scheduler-lifespan and the plain branch build
`application`, so register AFTER whichever `FastAPI(...)` is chosen, before/after `include_router`
is fine — middleware applies globally). Use:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.csrf import csrf_guard
...
application.add_middleware(BaseHTTPMiddleware, dispatch=csrf_guard)
```
Place the `add_middleware` call once, after `application` is created (e.g. right before the
`application.include_router(...)` block). Do not change any route or the static mount.

## Constraints / do-nots
- Touch ONLY `app/core/csrf.py` (new) and `app/main.py`. Do NOT edit any test or other file.
- Do NOT add any dependency (Starlette ships with FastAPI).
- Guard ONLY mutating methods; never 403 a GET/HEAD/OPTIONS/TRACE.
- Allow `same-origin`, `none`, and an absent `Sec-Fetch-Site` (so the app's own frontend and
  non-browser clients like the test suite keep working); block only `cross-site`/`same-site`.
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Review follow-up (SECOND delegation — Origin/Referer fallback)
Cross-family + security review found one residual gap: legacy browsers (Safari <16.4, old webviews)
omit `Sec-Fetch-Site` entirely but STILL send `Origin` on a cross-site POST/form, so the current
"absent → allow" fails open for them. Strengthen `app/core/csrf.py` so that when `Sec-Fetch-Site` is
absent, it falls back to `Origin`, then `Referer`. Keep everything else. New frozen tests
(`test_absent_fetch_site_*`) pin this.

Replace the guard body with this logic (only the absent-`Sec-Fetch-Site` branch is new):

```python
from urllib.parse import urlsplit


def _is_cross_origin(url_header: str, host: str) -> bool:
    """True only when the header carries a determinable host that differs from the request Host.
    An empty/opaque value (e.g. `Origin: null`) is not treated as cross-origin here (can't tell)."""
    netloc = urlsplit(url_header).netloc
    return netloc != "" and netloc != host


async def csrf_guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method.upper() not in _SAFE_METHODS:
        site = request.headers.get("sec-fetch-site")
        blocked = False
        if site is not None:
            blocked = site in _BLOCKED_FETCH_SITES
        else:
            # Legacy/non-Fetch-Metadata clients: fall back to Origin, then Referer, vs the Host.
            host = request.headers.get("host", "")
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            if origin is not None:
                blocked = _is_cross_origin(origin, host)
            elif referer is not None:
                blocked = _is_cross_origin(referer, host)
            # No Sec-Fetch-Site AND no Origin/Referer → a non-browser client → allowed.
        if blocked:
            return JSONResponse(
                status_code=403,
                content={"detail": "cross-site state-changing request refused"},
            )
    return await call_next(request)
```

Keep the `_SAFE_METHODS` / `_BLOCKED_FETCH_SITES` constants and the `JSONResponse` shape. `main.py`
wiring is unchanged. Keep lint/format/mypy clean.

## Scope
- `app/core/csrf.py`
- `app/main.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_csrf.py -q` → all 8 pass.
- `-m pytest -q` (full) → green (no existing API test should start failing; they send no
  `Sec-Fetch-Site`, so they are allowed).
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
