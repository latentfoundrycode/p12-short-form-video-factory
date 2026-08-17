import time


def run(ctx) -> None:
    ctx.emit({"t": "step", "name": "other", "key": "x", "label": "Other", "status": "running"})
    time.sleep(2)
    ctx.log("should not finish")
