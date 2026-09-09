"""Meter registry — how each cost meter is classified for display (PRD §7.1).

A meter is a provider's unit of spend. The three kinds cannot be added together:
  - **fiat**: real currency (e.g. OpenRouter, USD). All fiat providers SHARE ONE budget line —
    euros are euros regardless of who receives them, so their spend is summed together.
  - **credit**: provider-specific purchased credits (e.g. Higgsfield). Credit providers are NEVER
    combined with one another — one provider's credit is not comparable to another's — so each gets
    its own labelled line, named after the provider.
  - **quota**: a metered allowance read from the provider (e.g. ElevenLabs characters/month). Not a
    budget and not summed as spend; the Statistics spend view does not draw quota from records.

A meter not in the registry is treated as its own standalone `credit` line (never merged into the
fiat total), which is the safe default: an unknown unit must not be summed with anything else.

SKELETON — the `MeterInfo`/`METERS`/`meter_info` names are frozen by tests/core/test_meters.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# The kinds of meter, per PRD §7.1. Only "fiat" meters are ever summed together.
MeterKind = str  # one of: "fiat", "credit", "quota"


@dataclass(frozen=True)
class MeterInfo:
    """How a single meter is displayed: its kind (§7.1), provider label, and unit label."""

    kind: MeterKind
    provider: str
    unit: str


# Known meters. OpenRouter meters real currency (USD — what the provider actually reports; SFVF does
# not invent an FX conversion). Higgsfield meters provider credits. ElevenLabs is a monthly char
# quota (tracked, not summed as spend).
METERS: dict[str, MeterInfo] = {
    "openrouter": MeterInfo(kind="fiat", provider="OpenRouter", unit="usd"),
    "higgsfield": MeterInfo(kind="credit", provider="Higgsfield", unit="credits"),
    "elevenlabs": MeterInfo(kind="quota", provider="ElevenLabs", unit="chars"),
}


def meter_info(meter: str, registry: dict[str, MeterInfo] = METERS) -> MeterInfo:
    """Return the `MeterInfo` for `meter`, or a standalone-credit default for an unknown meter.

    An unknown meter must never be folded into the fiat total, so the fallback is a `credit` line
    labelled by the meter id itself (unit "credits").
    """
    raise NotImplementedError
