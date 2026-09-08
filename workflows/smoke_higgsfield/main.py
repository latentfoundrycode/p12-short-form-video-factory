"""Minimal live-path smoke workflow: one Higgsfield (Kling turbo) text-to-video call.

Purpose: validate the live Higgsfield adapter + the budget breaker end to end with the smallest
possible real spend (one `media.video.generate` call on a Kling text-to-video model). In dry_run the
SDK stubs the call as a local colour-bars clip (no key, no HTTP, no spend); in real mode it
exercises secret injection → budget reserve → the Higgsfield request → the downloaded clip.
"""

from sfvf import Context, Result, media

_MODEL = "kling-video/v2.5-turbo/pro/text-to-video"


def run(ctx: Context) -> Result:
    # v2.5-turbo/pro has no aspect_ratio (OpenAPI: prompt, duration, cfg_scale, negative_prompt).
    rel = media.video.generate(
        "A calm mountain lake at dawn, still water reflecting pine trees, gentle mist, no people.",
        model=_MODEL,
    )
    return Result(
        video=ctx.video_dir / rel,
        caption="higgsfield smoke ok",
        extra={"model": _MODEL},
    )
