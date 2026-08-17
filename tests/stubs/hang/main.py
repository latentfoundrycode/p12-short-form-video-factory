import time


def run(ctx) -> None:
    ctx.log("before hang")
    while True:
        time.sleep(60)
