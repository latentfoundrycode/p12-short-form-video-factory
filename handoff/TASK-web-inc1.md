# TASK — web-image-sourcing increment 1: `media.web` surface skeleton + capability vocab

> **Round 2 (cross-family Review B refinements).** Round 1 (already committed on this branch) built
> the skeleton. Review B required: (a) `source()` returns an ENRICHED result carrying provenance, not
> bare paths; (b) `source()` dry-run must NOT call the relevance gate; (c) `want` clamped to `>= 0`;
> (d) `search` validates `sources` and reflects the requested tier in the stub. Frozen RED contracts
> updated: `tests/integration/test_media_web_surface.py`. Apply ONLY these changes to
> `sdk/sfvf/media/web.py` (nothing else, no other file):

### R2.1 — add the `SourcedImage` TypedDict (next to `ImageCandidate`/`Relevance`)
```python
class SourcedImage(TypedDict):
    path: str
    candidate: ImageCandidate
    relevance: Relevance
```

### R2.2 — `search`: validate `sources`, reflect the tier
At the top of `search` (after `ctx = current_context()`), validate regardless of dry-run:
```python
    if not sources or any(s not in ("commons", "web") for s in sources):
        raise ValueError(f"sources must be a non-empty subset of ('commons','web'); got {sources!r}")
```
In the dry-run stub, tag each candidate by tier (cycling through `sources`) instead of hardcoding
`commons`/`CC0-1.0`:
```python
        tier = sources[i % len(sources)]
        licence = "unknown" if tier == "web" else "CC0-1.0"
```
and set `source=tier, licence=licence` on the `ImageCandidate`. (Keep the rest of the stub — url via
`_sha8`, deterministic, honours `limit`.)

### R2.3 — `source`: enriched return, clamp `want`, no relevance-gate call
Change the return annotation to `-> list[SourcedImage]`. In the dry-run branch:
```python
    if ctx.dry_run:
        n = max(0, want)                       # clamp — no negative-slice leakage
        candidates = search(query, sources=sources, limit=consider, licence=licence)[:n]
        stub = Relevance(relevant=True, score=1.0, reason="dry-run stub")
        return [
            SourcedImage(path=fetch(c), candidate=c, relevance=stub)
            for c in candidates
        ]
```
Do NOT call `check_relevance` here. The real path still `raise NotImplementedError(...)`.

Everything else (fetch, check_relevance dry-run returning the passing stub, the NotImplementedError
real paths) is unchanged. `ruff`/`format`/`mypy` clean; `git diff` shows only `sdk/sfvf/media/web.py`.

## Round 1 (already committed; retained for reference)


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

## Round 3 (dry-run honours `want`)
Cross-family Review B r2: `source(want=9, consider=9)` in dry-run returns 8 because the search stub
caps at `_STUB_POOL = 8`. In dry-run every stub passes, so `source` must return exactly `want` when
`want <= consider`. Fix: raise the stub pool cap so it is not the binding constraint for realistic
fan-out. In `sdk/sfvf/media/web.py` change `_STUB_POOL = 8` to `_STUB_POOL = 256` (a generous safety
bound; `search` still returns `min(limit, _STUB_POOL)`, so `search(limit=consider)` yields `consider`
candidates for any realistic `consider`, and `source` then honours `want <= consider`). ONLY that one
constant changes. Frozen test: `test_source_dry_run_honours_want_up_to_consider`.

## Round 4 (fan-out ceiling on `consider`)
Cross-family Review B r3: raising `_STUB_POOL` only moved the truncation; the contract needs an
explicit maximum, and `consider` needs a real cost-fanout ceiling (each candidate = a fetch + a VLM
check + a dry-run file). In `sdk/sfvf/media/web.py`:
1. Add a module constant `_MAX_CONSIDER = 50` (fan-out ceiling; a §10.2 default, revisitable).
2. In `source`, right after `ctx = current_context()` and BEFORE the `if ctx.dry_run:` branch, add:
   `if consider > _MAX_CONSIDER: raise ValueError(...)`.
Keep `_STUB_POOL = 256`. ONLY those two edits. Frozen test:
`test_source_rejects_consider_above_the_fanout_ceiling`.
