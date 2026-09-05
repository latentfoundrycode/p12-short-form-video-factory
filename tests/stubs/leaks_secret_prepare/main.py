def prepare(ctx) -> dict[str, str]:
    # A prepare step that (buggily) returns its own secret in the shared payload,
    # which is persisted to shared/result.json and threaded into each video's context.json.
    key = ctx.secret("OPENROUTER_API_KEY")
    return {"script": "hello", "leaked": key}


def run(ctx) -> None:
    ctx.emit({"t": "result", "video": "final.mp4", "caption": ctx.shared["script"]})
