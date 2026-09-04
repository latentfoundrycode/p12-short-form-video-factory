"""Per-provider rate limiter: one queue per provider (§5.5)."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class _ProviderState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    semaphore: threading.Semaphore = field(default_factory=lambda: threading.Semaphore(1))
    max_concurrency: int = 1
    min_interval_s: float = 0.0
    not_before: float = 0.0
    last_start: float = -math.inf


class RateLimiter:
    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._providers: dict[str, _ProviderState] = {}

    def _state(self, provider: str) -> _ProviderState:
        with self._lock:
            state = self._providers.get(provider)
            if state is None:
                state = _ProviderState()
                self._providers[provider] = state
            return state

    def configure(
        self,
        provider: str,
        *,
        max_concurrency: int = 1,
        min_interval_s: float = 0.0,
    ) -> None:
        state = self._state(provider)
        with state.lock:
            state.max_concurrency = max_concurrency
            state.min_interval_s = min_interval_s
            state.semaphore = threading.Semaphore(max_concurrency)

    @contextmanager
    def slot(self, provider: str) -> Iterator[None]:
        state = self._state(provider)
        semaphore = state.semaphore
        semaphore.acquire()
        try:
            with state.lock:
                now = self._monotonic()
                wait = max(
                    0.0,
                    state.not_before - now,
                    state.last_start + state.min_interval_s - now,
                )
                if wait > 0:
                    self._sleep(wait)
                state.last_start = self._monotonic()
            yield
        finally:
            semaphore.release()

    def penalize(self, provider: str, retry_after_s: float) -> None:
        state = self._state(provider)
        with state.lock:
            state.not_before = max(
                state.not_before,
                self._monotonic() + retry_after_s,
            )


LIMITER = RateLimiter()
