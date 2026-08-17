import time


def run(ctx) -> None:
    ctx.emit({"t": "gate", "name": "approve", "prompt": "ok"})
    time.sleep(1)
    ctx.log("after gate")
