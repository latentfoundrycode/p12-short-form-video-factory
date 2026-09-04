"""B-4b contract: per-provider rate-limiter scaffolding (§5.5).

A central limiter holds one queue per provider so a provider's own cap on requests-per-period
and concurrent-requests is respected regardless of how many steps run at once (§5.5, §3.1a).
Two things it must do: bound concurrency per provider, and honour a server-sent `Retry-After`
back-off (the provider told us to wait, so the next request to that provider waits). Providers
are independent — a back-off on one never delays another.

Timing is made deterministic with an injected clock/sleep (no real waiting); only the
concurrency test uses real threads, coordinated with events and generous timeouts.
"""

import threading

import pytest
from sfvf._ratelimit import RateLimiter


class FakeClock:
    """Deterministic monotonic clock + sleep: sleeping just advances `now` and is recorded."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)


def _limiter(clock: FakeClock) -> RateLimiter:
    return RateLimiter(monotonic=clock.monotonic, sleep=clock.sleep)


def test_min_interval_paces_successive_calls() -> None:
    clock = FakeClock()
    rl = _limiter(clock)
    rl.configure("openrouter", min_interval_s=5.0)
    with rl.slot("openrouter"):
        pass  # first call: nothing to wait for
    with rl.slot("openrouter"):
        pass  # second call: paced by the 5s minimum interval
    assert clock.sleeps == [pytest.approx(5.0)]


def test_retry_after_backs_off_next_slot() -> None:
    clock = FakeClock()
    rl = _limiter(clock)
    rl.penalize("openrouter", 30.0)  # provider said: wait 30s
    with rl.slot("openrouter"):
        pass
    assert clock.sleeps == [pytest.approx(30.0)]


def test_retry_after_takes_the_max_not_the_sum() -> None:
    clock = FakeClock()
    rl = _limiter(clock)
    rl.penalize("openrouter", 30.0)
    rl.penalize("openrouter", 10.0)  # shorter penalty must not shorten (nor extend by summing)
    with rl.slot("openrouter"):
        pass
    assert clock.sleeps == [pytest.approx(30.0)]


def test_providers_are_independent() -> None:
    clock = FakeClock()
    rl = _limiter(clock)
    rl.penalize("openrouter", 30.0)
    with rl.slot("higgsfield"):  # a different provider is unaffected
        pass
    assert clock.sleeps == []


def test_concurrency_cap_blocks_until_release() -> None:
    rl = RateLimiter()  # real clock/sleep for a real-threads concurrency check
    rl.configure("openrouter", max_concurrency=1)
    entered = threading.Event()
    release = threading.Event()
    second_done = threading.Event()

    def hold() -> None:
        with rl.slot("openrouter"):
            entered.set()
            release.wait(5)

    def second() -> None:
        with rl.slot("openrouter"):
            second_done.set()

    t1 = threading.Thread(target=hold)
    t1.start()
    assert entered.wait(5), "first slot never acquired"
    t2 = threading.Thread(target=second)
    t2.start()
    # While the first holder is inside its slot, the second cannot acquire (cap = 1).
    assert not second_done.wait(0.5)
    release.set()
    assert second_done.wait(5), "second slot never proceeded after release"
    t1.join(5)
    t2.join(5)
