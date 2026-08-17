import time


def run(ctx) -> None:
    ctx.emit({"t": "step", "name": "slow", "key": "x", "label": "Slow", "status": "running"})
    time.sleep(1)
    ctx.log("done")
