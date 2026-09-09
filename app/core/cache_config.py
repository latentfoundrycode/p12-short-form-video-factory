"""Configured maximum size of the cheap cache partition (Architecture §5.9, §8.7).

The cheap partition (renders/research) is LRU-evicted once it exceeds this many bytes; the paid
partition is never evicted, so this ceiling does not apply to it. Read from `SFVF_CACHE_MAX_BYTES`
(an integer byte count) with a conservative default. A missing, non-integer, or negative value
falls back to the default rather than failing a run — the cache is derived and eviction is a
best-effort housekeeping step, not a correctness gate.

SKELETON — signature frozen by tests/core/test_cache_config.py; the builder fills the body.
"""

from __future__ import annotations

# Default ceiling for the cheap partition when unset. Per cache root (workflow + mode) in v1; a
# single global ceiling across all partitions (§8.7) is a later refinement — see HARDENING.
DEFAULT_CACHE_MAX_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB

_ENV_VAR = "SFVF_CACHE_MAX_BYTES"


def cache_max_bytes() -> int:
    """Return the configured cheap-cache ceiling in bytes, or the default when unset/invalid."""
    raise NotImplementedError
