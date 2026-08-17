import signal
import sys
import time
from pathlib import Path


def _install_soft_handler() -> None:
    def _exit_clean(*_args: object) -> None:
        sys.exit(0)

    signal.signal(signal.SIGTERM, _exit_clean)
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _exit_clean)


def prepare(ctx) -> dict[str, str]:
    _install_soft_handler()
    sentinel = Path(ctx.paths.video) / ".stop"
    for _ in range(200):
        if sentinel.is_file():
            ctx.log("prep saw stop")
            return {"cancelled": "1"}
        ctx.heartbeat("prep", waiting_on="test")
        time.sleep(0.05)
    raise RuntimeError("prep stop sentinel never appeared")


def run(ctx) -> None:
    ctx.log("should not run")
