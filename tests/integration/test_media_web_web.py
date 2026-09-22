"""Frozen contract — web-image-sourcing increment 6: the SerpApi `web` tier (paid, key-gated).

`media.web.search(..., sources=("web",))` real path calls the SerpApi Google Images API
(`GET https://serpapi.com/search?engine=google_images`) with the workflow's `SERPAPI_API_KEY`
secret, `safe=active` (safeSearch strict — the owner's chosen content-safety posture), and maps each
`images_results` item to an `ImageCandidate` tagged `source="web"`, `licence="unknown"`
(owner-decided: web-tier images may appear in produced videos). Exercised against MOCKED HTTP only —
no network, no real spend. `web.images.web` is offered ONLY when the key is configured.

Seam the adapter exposes (patched here): `sfvf.providers.serpapi._client() -> httpx2.Client`.

SerpApi images_results item -> ImageCandidate: source="web"; url=item["original"] (full-res image);
thumbnail=item["thumbnail"]; licence="unknown"; width/height from original_width/original_height;
title=item["title"]; rank=position. A null `original` is skipped; an `unsafe` item is dropped.
"""

import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.providers import capabilities_offered, openverse, serpapi

_BASE = "https://serpapi.com"
_KEY = "serpapi-fake-key-not-real"

_RESULTS = [
    {
        "position": 1,
        "thumbnail": "https://serpapi.com/thumb/0.jpg",
        "original": "https://cdn.example.invalid/full-0.jpg",
        "original_width": 3000,
        "original_height": 2000,
        "title": "Red barn at dusk",
        "link": "https://site0.example.invalid/page",
        "source": "House Beautiful",
    },
    {
        "position": 2,
        "thumbnail": "https://serpapi.com/thumb/1.jpg",
        "original": "https://cdn.example.invalid/full-1.jpg",
        "original_width": 1600,
        "original_height": 1200,
        "title": "Barn in a field",
        "link": "https://site1.example.invalid/page",
        "source": "Flickr",
    },
]


def _ctx(tmp: Path, *, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            secrets={"SERPAPI_API_KEY": _KEY} if secrets is None else secrets,
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

    monkeypatch.setattr(serpapi, "_client", _client)
    return seen


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _ok(_request: httpx2.Request, _n: int) -> httpx2.Response:
    return httpx2.Response(200, json={"search_metadata": {}, "images_results": _RESULTS})


# --- request shape + candidate mapping ----------------------------------------------------------


def test_web_search_hits_serpapi_google_images_and_maps_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    out = _run(
        _ctx(tmp_path),
        lambda: media.web.search("red barn", sources=("web",), limit=5),
    )
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "GET"
    assert str(req.url).split("?")[0].endswith("/search")
    assert req.url.params.get("engine") == "google_images"
    assert req.url.params.get("q") == "red barn"
    assert req.url.params.get("safe") == "active", "safeSearch must be strict (owner decision)"
    assert req.url.params.get("api_key") == _KEY, "the SERPAPI_API_KEY secret drives the call"

    assert [c["url"] for c in out] == [r["original"] for r in _RESULTS]
    first = out[0]
    assert first["source"] == "web"
    assert first["licence"] == "unknown", "web-tier licence is always unknown"
    assert first["thumbnail"] == _RESULTS[0]["thumbnail"]
    assert first["title"] == _RESULTS[0]["title"]
    assert first["width"] == 3000 and first["height"] == 2000
    assert first["rank"] == 0 and out[1]["rank"] == 1
    assert first["attribution"].strip(), "a web result carries a non-empty attribution"
    json.dumps(out)


def test_web_search_sends_safe_active_content_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert seen[0].url.params.get("safe") == "active"


def test_web_search_returns_empty_for_a_nonpositive_limit_without_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ok)
    for bad in (0, -1):
        out = _run(
            _ctx(tmp_path), lambda n=bad: media.web.search("barn", sources=("web",), limit=n)
        )
        assert out == []
    assert seen == []


# --- robustness: untrusted provider payload -----------------------------------------------------


def test_web_search_skips_null_original_and_unsafe_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"original": None, "title": "no url"},  # null original -> skipped
        {
            "original": "https://cdn.example.invalid/nsfw.jpg",
            "unsafe": True,
            "title": "nsfw",
        },  # dropped
        {
            "original": "https://cdn.example.invalid/ok.jpg",
            "thumbnail": None,
            "title": None,
            "original_width": None,
            "original_height": None,
        },
    ]

    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, json={"images_results": rows})

    _install_mock(monkeypatch, handler)
    out = _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert [c["url"] for c in out] == ["https://cdn.example.invalid/ok.jpg"]
    c = out[0]
    assert c["licence"] == "unknown"
    assert c["thumbnail"] == "" and c["title"] == ""
    assert c["width"] == 0 and c["height"] == 0
    json.dumps(out)


def test_web_search_tolerates_a_non_list_images_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(200, json={"images_results": 5})

    _install_mock(monkeypatch, handler)
    out = _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert out == []


def test_web_search_raises_a_clean_error_without_leaking_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(_request: httpx2.Request, _n: int) -> httpx2.Response:
        return httpx2.Response(401, json={"error": "Invalid API key"})

    _install_mock(monkeypatch, bad)
    with pytest.raises(RuntimeError) as exc:
        _run(_ctx(tmp_path), lambda: media.web.search("barn", sources=("web",)))
    assert _KEY not in str(exc.value), "the API key must never appear in the error"


# --- capability gating on the secret ------------------------------------------------------------


def test_web_capability_is_offered_only_when_the_key_is_configured() -> None:
    assert "web.images.web" in capabilities_offered({"SERPAPI_API_KEY"})
    assert "web.images.web" not in capabilities_offered(set())
    # the keyless commons capability is offered regardless
    assert "web.images.commons" in capabilities_offered(set())


# --- mixed commons+web dispatch (both tiers, URL-deduplicated) ----------------------------------


def test_mixed_commons_and_web_dispatches_both_tiers_and_dedups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A ("commons","web") request now dispatches BOTH real tiers and URL-deduplicates the union
    # (design §3.1). One url is shared by both tiers to prove the dedup keeps first-seen order.
    shared = "https://cdn.example.invalid/full-0.jpg"  # equals _RESULTS[0]["original"]

    def openverse_client() -> httpx2.Client:
        def handler(_req: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={
                    "results": [
                        {
                            "url": shared,  # duplicate of the web tier's first hit
                            "license": "cc0",
                            "license_version": "1.0",
                            "attribution": "x",
                            "title": "commons dup",
                        },
                        {
                            "url": "https://cdn.example.invalid/commons-only.jpg",
                            "license": "by",
                            "license_version": "4.0",
                            "attribution": "y",
                            "title": "commons only",
                        },
                    ]
                },
            )

        return httpx2.Client(
            base_url="https://api.openverse.org/v1", transport=httpx2.MockTransport(handler)
        )

    monkeypatch.setattr(openverse, "_client", openverse_client)
    _install_mock(monkeypatch, _ok)  # serpapi returns _RESULTS (first url == shared)

    out = _run(
        _ctx(tmp_path), lambda: media.web.search("barn", sources=("commons", "web"), limit=5)
    )
    urls = [c["url"] for c in out]
    # commons first (rank order), then web; the shared url appears once (first-seen = commons)
    assert urls == [
        shared,
        "https://cdn.example.invalid/commons-only.jpg",
        "https://cdn.example.invalid/full-1.jpg",
    ]
    assert out[0]["source"] == "commons", "first-seen wins for a duplicate url"
