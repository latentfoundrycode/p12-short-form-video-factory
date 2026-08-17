def prepare(ctx) -> list[str]:
    return ["not", "a", "dict"]


def run(ctx) -> None:
    ctx.log("ok")
