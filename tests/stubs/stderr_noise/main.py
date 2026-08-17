import sys


def run(ctx) -> None:
    print("lib noise", file=sys.stderr)
    ctx.log("after stderr")
