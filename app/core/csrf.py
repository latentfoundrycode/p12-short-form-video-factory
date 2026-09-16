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
