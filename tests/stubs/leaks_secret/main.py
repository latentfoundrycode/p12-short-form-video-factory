def run(ctx) -> None:
    # A workflow that (buggily) puts its own secret into the structured result.
    key = ctx.secret("OPENROUTER_API_KEY")
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "hi", "extra": {"leaked": key}})
