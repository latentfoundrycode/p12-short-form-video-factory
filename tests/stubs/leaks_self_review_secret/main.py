def run(ctx) -> None:
    # An injected secret surfacing in a self_review field (a composition violation detail) must be
    # redacted in video.json — the self_review block is a write path, like cost and the result.
    leaked = ctx.secret("OPENROUTER_API_KEY")
    ctx.emit(
        {
            "t": "self_review",
            "passed": False,
            "structural": {
                "duration_s": 5.0,
                "width": 1080,
                "height": 1920,
                "has_audio": False,
                "has_captions": False,
            },
            "content": None,
            "composition": {
                "checked": 1,
                "violations": [{"kind": "missing-font", "detail": f"font url {leaked} failed"}],
            },
            "failures": [f"composition: missing-font: font url {leaked} failed"],
        }
    )
    ctx.emit({"t": "result", "video": "final.mp4"})
