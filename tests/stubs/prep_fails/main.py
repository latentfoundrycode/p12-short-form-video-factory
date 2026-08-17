def prepare(ctx) -> None:
    raise RuntimeError("prep boom")


def run(ctx) -> None:
    ctx.log("should not run")
