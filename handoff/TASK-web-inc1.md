# TASK — web-image-sourcing increment 1: `media.web` surface skeleton + capability vocab

Frozen RED contracts:
- `tests/integration/test_media_web_surface.py`
- `tests/registry/test_web_images_vocab.py`

Authoritative design: `docs/DESIGN-web-image-sourcing.md` (§3 surface, §5 capabilities). This increment
builds the SURFACE SKELETON only — dry-run stubs + the capability vocabulary. The real (non-dry-run)
paths are NOT built yet and must raise `NotImplementedError` (later increments fill them). No network,
no provider, no adapter this increment.

## Scope (exactly these three files)
- `sdk/sfvf/media/web.py` (new)
- `sdk/sfvf/media/__init__.py` (add `web`)
- `app/registry/validate.py` (two new capability strings)

Do NOT touch tests, docs/, handoff/, requirements, CI, the provider registry, or any adapter.

## 1. `sdk/sfvf/media/web.py` (new)

```python
from __future__ import annotations

from typing import TypedDict

from .._ffmpeg import solid_image
from .._runtime import current_context
from .graphics import _artifact, _sha8

_VISION_MODEL = "openai/gpt-4o"   # default vision model for check_relevance (revisited at increment 4)
_STUB_POOL = 8                     # dry-run search returns up to this many deterministic candidates


class ImageCandidate(TypedDict):
    source: str
    url: str
    thumbnail: str
    licence: str
    attribution: str
    width: int
    height: int
    title: str
    rank: int


class Relevance(TypedDict):
    relevant: bool
    score: float
    reason: str


def search(
    query: str,
    *,
    sources: tuple[str, ...] = ("commons",),
    limit: int = 10,
    licence: str | None = None,
) -> list[ImageCandidate]:
    ctx = current_context()
    if ctx.dry_run:
        n = max(0, min(limit, _STUB_POOL))
        return [
            ImageCandidate(
                source="commons",
                url=f"https://example.invalid/{_sha8(['web.search', query, i])}.jpg",
                thumbnail=f"https://example.invalid/{_sha8(['web.thumb', query, i])}-t.jpg",
                licence="CC0-1.0",
                attribution="dry-run stub",
                width=800,
                height=600,
                title=f"{query} — stub {i}",
                rank=i,
            )
            for i in range(n)
        ]
    raise NotImplementedError("media.web.search real path is built in increment 2 (commons tier)")


def fetch(candidate: ImageCandidate) -> str:
    ctx = current_context()
    if ctx.dry_run:
        stem = _sha8(["web.fetch", candidate["url"]])
        dest, rel = _artifact(ctx, f"web-{stem}.png")
        solid_image(dest, width=64, height=64)
        return rel
    raise NotImplementedError("media.web.fetch real path is built in increment 3 (download + safety)")


def check_relevance(image: str, *, subject: str, model: str = _VISION_MODEL) -> Relevance:
    ctx = current_context()
    if ctx.dry_run:
        return Relevance(relevant=True, score=1.0, reason="dry-run stub")
    raise NotImplementedError("media.web.check_relevance real path is built in increment 4 (VLM gate)")


def source(
    query: str,
    *,
    subject: str,
    sources: tuple[str, ...] = ("commons",),
    want: int = 1,
    consider: int = 8,
    min_score: float = 0.6,
    licence: str | None = None,
) -> list[str]:
    ctx = current_context()
    if ctx.dry_run:
        # Short-circuit: compose the search + fetch STUBS and return `want` paths. Do NOT call
        # check_relevance (design §3.2) — its gate is irrelevant in dry-run.
        candidates = search(query, sources=sources, limit=consider, licence=licence)
        return [fetch(c) for c in candidates[:want]]
    raise NotImplementedError("media.web.source real path is built in increment 5")
```

Notes:
- `current_context()` is called first in every function, so a missing active context raises
  `RuntimeError` before the dry-run branch — satisfying the require-context test.
- The dry-run search stub is deterministic (derived from `query`/index via `_sha8`), JSON-native, and
  honours `limit`. `fetch` writes a real 64×64 stub PNG via `_artifact` + `solid_image` and returns the
  workspace-relative path, exactly like `media.image.generate`'s stub.
- `_sha8` and `_artifact` are imported from `.graphics` (same as `media/image.py`).

## 2. `sdk/sfvf/media/__init__.py`
Add `web` to the submodule import and to `__all__`, keeping alphabetical order:
```python
from . import edit, graphics, image, speech, video, web
__all__ = ["edit", "finalize", "graphics", "image", "speech", "video", "web"]
```
(Keep the existing `from ..finalize import finalize` line.)

## 3. `app/registry/validate.py`
Add two entries to the `KNOWN_CAPABILITIES` frozenset (alongside `agents.vision`):
```python
    "web.images.commons",
    "web.images.web",
```

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_surface.py tests/registry/test_web_images_vocab.py -q` — all pass.
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_providers_registry.py tests/registry/ -q` — still pass (no regression; you did NOT touch the provider registry).
- `ruff check` + `ruff format --check` + `mypy` clean on `sdk/sfvf/media/web.py`, `sdk/sfvf/media/__init__.py`, `app/registry/validate.py`.
- `git diff` shows exactly the three files above changed/created.
