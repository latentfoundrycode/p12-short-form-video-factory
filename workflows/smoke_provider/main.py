"""Generic provider smoke: one image or video call to the selected model, for an attended
live check.

Dry run (the default in tests) produces a stub via the SDK; a real run makes one metered/priced call
through the provider layer. One call, budget floors from budget.toml, stop-and-report.
"""

from sfvf import Context, Result, media


def run(ctx: Context) -> Result:
    kind = str(ctx.params["kind"])
    model = str(ctx.params["model"])
    if kind == "image":
        rel = media.image.generate(
            "smoke test: a simple teal robot on a plain white background",
            model=model,
        )
    else:
        rel = media.video.generate(
            "smoke test: a calm mountain lake at dawn, gentle mist, no people",
            model=model,
            duration_s=4.0,
        )
    return Result(
        video=ctx.video_dir / rel,
        caption="provider smoke ok",
        extra={"kind": kind, "model": model},
    )
