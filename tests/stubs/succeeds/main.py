def run(ctx) -> None:
    ctx.log("ok")
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "hello"})
