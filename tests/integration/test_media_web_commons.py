"""Frozen contract — web-image-sourcing increment 2: the Openverse `commons` tier.

`media.web.search(..., sources=("commons",))` real path calls the Openverse image API
(`GET https://api.openverse.org/v1/images/`) and maps each result to an `ImageCandidate`. Exercised
against MOCKED HTTP only — no network. Openverse allows ANONYMOUS search, so the request carries NO
Authorization header (the provider is keyless).

Seam the adapter exposes (patched here, never hitting the network):
  * `sfvf.providers.openverse._client() -> httpx2.Client` — the real path builds its client via it.

Field mapping (Openverse result -> ImageCandidate):
  source="commons"; url=result["url"] (the direct image file, NOT foreign_landing_url);
  thumbnail=result["thumbnail"]; licence="<license> <license_version>";
  attribution=result["attribution"]; width/height; title; rank = position in results.
"""

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.providers import openverse

_BASE = "https://api.openverse.org/v1"

_RESULTS = [
    {
        "id": "8624ba61-57f1-4f98-8a85-ece206c319cf",
        "title": "Red barn at dusk",
        "url": "https://live.example.invalid/full-0.jpg",
        "thumbnail": "https://api.openverse.org/v1/images/8624ba61/thumb/",
        "creator": "Jane Doe",
        "license": "cc0",
        "license_version": "1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": '"Red barn at dusk" by Jane Doe is marked with CC0 1.0.',
        "width": 3000,
        "height": 2000,
        "source": "flickr",
        "foreign_landing_url": "https://flickr.example.invalid/photos/jane/0/",
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "title": "Barn in a field",
        "url": "https://live.example.invalid/full-1.jpg",
        "thumbnail": "https://api.openverse.org/v1/images/22222222/thumb/",
        "creator": "John Roe",
        "license": "by-sa",
        "license_version": "4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": '"Barn in a field" by John Roe is licensed under CC BY-SA 4.0.',
        "width": 1600,
        "height": 1200,
        "source": "wikimedia",
        "foreign_landing_url": "https://commons.example.invalid/wiki/File:Barn.jpg",
    },
]


def _ctx(tmp: Path) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
        )
    )


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, len(seen))

    def _client() -> httpx2.Client:
        return httpx2.Client(base_url=_BASE, transport=httpx2.MockTransport(wrapped))

    monkeypatch.setattr(openverse, "_client", _client)
    return seen


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _ok(_request: httpx2.Request, _n: int) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "result_count": 100,
            "page_count": 50,
            "page_size": len(_RESULTS),
            "page": 1,
            "results": _RESULTS,
        },
    )


def test_commons_search_hits_openverse_images_and_maps_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.search("red barn", sources=("commons",), limit=5, licence="cc0"),
    )
    # request: GET /images/ with q, page_size, license; anonymous (no auth header).
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "GET"
    assert str(req.url).split("?")[0].endswith("/images/")
    assert req.url.params.get("q") == "red barn"
    assert req.url.params.get("page_size") == "5"
    assert req.url.params.get("license") == "cc0"
    assert "authorization" not in {k.lower() for k in req.headers}

    # mapping: one ImageCandidate per result, in order, tagged as the commons tier.
    assert [c["url"] for c in out] == [r["url"] for r in _RESULTS]
    first = out[0]
    assert first["source"] == "commons"
    assert first["thumbnail"] == _RESULTS[0]["thumbnail"]
    assert first["title"] == _RESULTS[0]["title"]
    assert first["width"] == 3000 and first["height"] == 2000
    assert first["rank"] == 0 and out[1]["rank"] == 1
    assert first["attribution"] == _RESULTS[0]["attribution"]
    # licence carries the code and version, and is NOT "unknown" for the commons tier.
    assert "cc0" in first["licence"] and "1.0" in first["licence"]
    assert out[1]["licence"] != "unknown" and "by-sa" in out[1]["licence"]
    json.dumps(out)


def test_commons_search_omits_license_param_when_not_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    _run(tmp_path and _ctx(tmp_path), lambda: media.web.search("barn", sources=("commons",)))
    assert "license" not in seen[0].url.params


def test_commons_search_raises_a_clean_error_on_openverse_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(
            400,
            json={"error": "InputError", "detail": "bad license", "fields": ["license"]},
        )

    _install_mock(monkeypatch, bad)
    with pytest.raises(RuntimeError):
        _run(
            _ctx(tmp_path),
            lambda: media.web.search("barn", sources=("commons",), licence="bogus"),
        )
