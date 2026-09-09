def run(ctx) -> None:
    # A workflow that (buggily) puts its injected secret into a cost event's meter. The per-video
    # cost block written to video.json must redact it, like every other write path (§8).
    key = ctx.secret("OPENROUTER_API_KEY")
    ctx.emit({"t": "cost", "meter": key, "unit": "usd", "amount": 0.01, "cached": False})
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "cost secret"})
