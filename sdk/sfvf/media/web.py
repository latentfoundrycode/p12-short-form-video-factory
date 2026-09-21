from __future__ import annotations

from typing import TypedDict

from .._ffmpeg import solid_image
from .._runtime import current_context
from .graphics import _artifact, _sha8

# default vision model for check_relevance (revisited at increment 4)
_VISION_MODEL = "openai/gpt-4o"
_STUB_POOL = 256  # dry-run search returns up to this many deterministic candidates
_MAX_CONSIDER = 50


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


class SourcedImage(TypedDict):
    path: str
    candidate: ImageCandidate
    relevance: Relevance


def search(
    query: str,
    *,
    sources: tuple[str, ...] = ("commons",),
    limit: int = 10,
    licence: str | None = None,
) -> list[ImageCandidate]:
    ctx = current_context()
    if not sources or any(s not in ("commons", "web") for s in sources):
        raise ValueError(
            f"sources must be a non-empty subset of ('commons','web'); got {sources!r}"
        )
    if ctx.dry_run:
        n = max(0, min(limit, _STUB_POOL))
        candidates: list[ImageCandidate] = []
        for i in range(n):
            tier = sources[i % len(sources)]
            licence = "unknown" if tier == "web" else "CC0-1.0"
            candidates.append(
                ImageCandidate(
                    source=tier,
                    url=f"https://example.invalid/{_sha8(['web.search', query, i])}.jpg",
                    thumbnail=f"https://example.invalid/{_sha8(['web.thumb', query, i])}-t.jpg",
                    licence=licence,
                    attribution="dry-run stub",
                    width=800,
                    height=600,
                    title=f"{query} — stub {i}",
                    rank=i,
                )
            )
        return candidates
    raise NotImplementedError("media.web.search real path is built in increment 2 (commons tier)")


def fetch(candidate: ImageCandidate) -> str:
    ctx = current_context()
    if ctx.dry_run:
        stem = _sha8(["web.fetch", candidate["url"]])
        dest, rel = _artifact(ctx, f"web-{stem}.png")
        width = 16 + int(stem[6:], 16)  # last byte -> width 16..271; colour carries the first 6 hex
        solid_image(dest, width=width, height=64, color=f"0x{stem[:6]}")
        return rel
    raise NotImplementedError(
        "media.web.fetch real path is built in increment 3 (download + safety)"
    )


def check_relevance(image: str, *, subject: str, model: str = _VISION_MODEL) -> Relevance:
    ctx = current_context()
    if ctx.dry_run:
        return Relevance(relevant=True, score=1.0, reason="dry-run stub")
    raise NotImplementedError(
        "media.web.check_relevance real path is built in increment 4 (VLM gate)"
    )


def source(
    query: str,
    *,
    subject: str,
    sources: tuple[str, ...] = ("commons",),
    want: int = 1,
    consider: int = 8,
    min_score: float = 0.6,
    licence: str | None = None,
) -> list[SourcedImage]:
    ctx = current_context()
    if consider > _MAX_CONSIDER:
        raise ValueError(f"consider={consider} exceeds the fan-out ceiling {_MAX_CONSIDER}")
    if ctx.dry_run:
        n = max(0, want)  # clamp — no negative-slice leakage
        candidates = search(query, sources=sources, limit=consider, licence=licence)[:n]
        return [
            SourcedImage(
                path=fetch(c),
                candidate=c,
                relevance=Relevance(relevant=True, score=1.0, reason="dry-run stub"),
            )
            for c in candidates
        ]
    raise NotImplementedError("media.web.source real path is built in increment 5")
