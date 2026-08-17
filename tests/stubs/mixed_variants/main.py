def run(ctx) -> None:
    index = int(ctx.paths.video.name)
    if index % 2 == 0:
        raise RuntimeError(f"fail {ctx.paths.video.name}")
    ctx.log(f"ok {ctx.paths.video.name}")
    ctx.emit({"t": "result", "video": "final.mp4", "caption": ctx.paths.video.name})
