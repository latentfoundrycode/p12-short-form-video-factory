def prepare(ctx) -> dict[str, str]:
    ctx.log("prep-ok")
    return {"script": "hello from prep"}


def run(ctx) -> None:
    ctx.log(ctx.shared["script"])
    ctx.emit({"t": "result", "video": "final.mp4", "caption": ctx.shared["script"]})
