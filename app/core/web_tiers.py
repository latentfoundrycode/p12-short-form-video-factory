"""Load the owner-controlled web-image tier off-switch (DESIGN §5).

Mirrors the budget activation layer: an env-gated owner setting is read at app start and
injected into each run's context so the SDK re-checks it before any dispatch. Unset/empty
means nothing is disabled (design default: enabled when the key is present).
"""

from __future__ import annotations

import os


def load_disabled_web_tiers() -> list[str]:
    """Return the owner-disabled web-image tiers, or [] when none are disabled.

    `SFVF_DISABLE_WEB_TIERS` unset or blank → []. Otherwise split on commas, strip each
    token, drop blanks, lowercase, and de-duplicate while preserving first-seen order.
    """
    raw = os.environ.get("SFVF_DISABLE_WEB_TIERS")
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        tier = part.strip().lower()
        if not tier or tier in seen:
            continue
        seen.add(tier)
        out.append(tier)
    return out
