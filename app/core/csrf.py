from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Reads are not state-changing; OPTIONS is the CORS preflight. Only guard mutating methods.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Values a browser stamps for a request from a DIFFERENT origin. `same-origin`, `none`, and an
# absent header (non-browser clients) are allowed.
_BLOCKED_FETCH_SITES = frozenset({"cross-site", "same-site"})


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
