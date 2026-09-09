def run(ctx) -> None:
    # A workflow that (buggily) puts its injected secret into a forecast's meter. The forecast block
    # written to request.json is a write path and must redact it (§8).
    key = ctx.secret("OPENROUTER_API_KEY")
    ctx.forecast(key, "usd", 1.0, note=key)
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "forecast secret"})
