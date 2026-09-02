from sfvf import Result


def run(ctx):
    # Write the finished file where the real one would go, then return it by
    # Path. The runner turns a returned Result into the `result` event the
    # supervisor records, with the video path made relative to the video folder.
    out = ctx.artifacts / "final.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"stub-final")
    return Result(
        video=out,
        caption="hi",
        hashtags=["a", "b"],
        notes="n",
        extra={"k": 1},
    )
