import signal
import time


def run(ctx) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, signal.SIG_IGN)
    ctx.log("ignoring stop")
    time.sleep(8)
