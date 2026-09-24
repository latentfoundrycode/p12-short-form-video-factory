def prepare(ctx) -> dict[str, str]:
    # Prepare-phase spend: a real cost incurred ONCE per run before any video (e.g. web-sourcing a
    # shared asset behind a paid VLM relevance check). record_cost emits a cost event the engine
    # aggregates — this is the spend that must land in request.prepare_cost.
    ctx.record_cost("openrouter", "usd", 0.05, "prepare-vlm-check")
    return {"asset": "shared-thing"}


def run(ctx) -> None:
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "prepare cost stub"})
