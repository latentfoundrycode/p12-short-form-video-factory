from __future__ import annotations

import importlib
from typing import Any

from .._ffmpeg import color_bars
from .._runtime import current_context
from ..providers import CapabilityError, resolve
from ..providers._refs import image_ref_url
from .graphics import _artifact, _sha8

_DEFAULT_DURATION_S = 5.0
_WIDTH = 1080
_HEIGHT = 1920
_FPS = 30


def generate(
    prompt: str,
    *,
    model: str,
    first_frame: str | None = None,
    last_frame: str | None = None,
    refs: list[Any] | None = None,
    duration_s: float | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    ctx = current_context()
    dest, rel = _artifact(
        ctx,
        f"video-{_sha8([prompt, model, first_frame, last_frame, refs, duration_s, extra])}.mp4",
    )
    if ctx.dry_run:
        color_bars(
            dest,
            duration_s=duration_s or _DEFAULT_DURATION_S,
            width=_WIDTH,
            height=_HEIGHT,
            fps=_FPS,
        )
        return rel
    provider, mdl = resolve(model)
    if mdl.kind != "video" or "video.generate" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} cannot generate video")
    if refs and "video.refs" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} does not support reference conditioning")
    if (first_frame or last_frame) and "video.first_frame" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} does not support first/last-frame conditioning")
    secrets = {n: ctx.secret(n) for n in provider.secret_names}
    first_url = image_ref_url(ctx, first_frame) if first_frame else None
    last_url = image_ref_url(ctx, last_frame) if last_frame else None
    ref_urls = [image_ref_url(ctx, r["path"]) for r in (refs or [])]
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    estimate = adapter.video_estimate(mdl, duration_s, extra)
    with ctx._budget_reserved(provider.meter, provider.unit, estimate=estimate) as token:
        out, cost = adapter.generate_video(
            prompt,
            model=mdl,
            provider=provider,
            first_frame_url=first_url,
            last_frame_url=last_url,
            ref_urls=ref_urls,
            duration_s=duration_s,
            extra=extra,
            secrets=secrets,
            ctx=ctx,
        )
    ctx.record_cost(provider.meter, provider.unit, cost.amount, cost.source, token=token)
    dest.write_bytes(out.data)
    return rel
