def run(ctx) -> None:
    # A later forecast for the same meter supersedes the earlier one; other meters accumulate.
    ctx.forecast("higgsfield", "credits", 500, note="early")
    ctx.forecast("higgsfield", "credits", 720, note="60 shots")
    ctx.forecast("openrouter", "usd", 1.2)
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "forecast stub"})
