def prepare(ctx) -> None:
    # The standard prepare contract: returns None, so the runner writes result.json = null.
    # The _run_prepare finally must scrub that null result.json WITHOUT crashing (H18 round-2).
    return None


def run(ctx) -> None:
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "ok"})
