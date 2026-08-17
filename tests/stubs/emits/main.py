def run(ctx) -> None:
    ctx.stage(1, 2, "start")
    ctx.log("hello")
    ctx.heartbeat("work", waiting_on="test")
    ctx.stage(2, 9, "counted later")
