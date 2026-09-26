"""media.image.price / media.video.price — pre-call price estimates for budgeting.

A workflow's approval gate must show what a paid render will actually RESERVE, which is
max(adapter price, owner estimate) — so it needs the adapter's price without making the call.
`media.image.price(model)` and `media.video.price(model, duration_s)` expose that (pure registry
lookups, no network, no context), for the SSN gate cost estimate (H-SSN-17 / Review B blocker).

Supervisor-authored (RED-first); the builder adds `price` to sdk/sfvf/media/{image,video}.py.
"""

from __future__ import annotations

from sfvf import media

_IMAGE_MODEL = "google/gemini-3.1-flash-image"
_CLIP_MODEL = "byteplus/seedance-2.5"


def test_image_price_is_positive() -> None:
    p = media.image.price(_IMAGE_MODEL)
    assert isinstance(p, float)
    assert p > 0.0


def test_video_price_scales_with_duration() -> None:
    short = media.video.price(_CLIP_MODEL, 1.0)
    long = media.video.price(_CLIP_MODEL, 5.0)
    assert isinstance(short, float) and isinstance(long, float)
    assert short > 0.0
    assert long > short  # a longer clip costs more
