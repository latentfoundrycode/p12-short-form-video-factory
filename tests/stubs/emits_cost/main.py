def run(ctx) -> None:
    # Two non-cached openrouter costs sum into actual and uncached; one cached higgsfield cost
    # counts toward uncached only (free this run, but would cost fresh).
    ctx.emit({"t": "cost", "meter": "openrouter", "unit": "usd", "amount": 0.02, "cached": False})
    ctx.emit({"t": "cost", "meter": "openrouter", "unit": "usd", "amount": 0.01, "cached": False})
    ctx.emit({"t": "cost", "meter": "higgsfield", "unit": "credits", "amount": 12, "cached": True})
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "cost stub"})
