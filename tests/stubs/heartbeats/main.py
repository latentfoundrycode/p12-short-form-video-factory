import time


def run(ctx) -> None:
    for _ in range(15):
        ctx.heartbeat("work", waiting_on="test")
        time.sleep(0.1)
    ctx.log("done")
