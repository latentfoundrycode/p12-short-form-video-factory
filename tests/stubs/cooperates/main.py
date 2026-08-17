import signal
import sys
import time
from pathlib import Path


def run(ctx) -> None:
    def _exit_clean(*_args: object) -> None:
        sys.exit(0)

    signal.signal(signal.SIGTERM, _exit_clean)
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _exit_clean)

    sentinel = Path(ctx.paths.video) / ".stop"
    for _ in range(200):
        if sentinel.is_file():
            ctx.log("saw stop")
            return
        ctx.heartbeat("work", waiting_on="test")
        time.sleep(0.05)
    raise RuntimeError("stop sentinel never appeared")
