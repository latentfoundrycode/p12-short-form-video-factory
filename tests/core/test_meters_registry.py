"""Frozen contract — Stage P, P-8a: the registry <-> METERS cross-check.

Every provider in the media registry (`sfvf.providers.PROVIDERS`) must have a matching entry in the
app's display-meter table (`app.core.meters.METERS`), and that entry's kind/unit must agree with the
registry row — so a run's cost is always classified for display the same way it is metered. Meters
that have no registry provider (e.g. `elevenlabs`, a quota meter) are allowed to remain in METERS;
the check is one-directional (every registry provider -> a consistent meter entry), not the reverse.
"""

from __future__ import annotations

from sfvf.providers import PROVIDERS

from app.core.meters import METERS


def test_every_registry_provider_has_a_consistent_meter_entry() -> None:
    for pid, provider in PROVIDERS.items():
        assert pid in METERS, f"registry provider {pid!r} has no METERS entry"
        info = METERS[pid]
        assert info.kind == provider.meter_kind, (
            f"{pid}: METERS kind {info.kind!r} != registry meter_kind {provider.meter_kind!r}"
        )
        assert info.unit == provider.unit, (
            f"{pid}: METERS unit {info.unit!r} != registry unit {provider.unit!r}"
        )
        assert info.provider, f"{pid}: METERS entry has an empty provider label"


def test_registry_meter_id_equals_provider_id() -> None:
    # The registry pins meter == id for every provider; the METERS key is that same id.
    for pid, provider in PROVIDERS.items():
        assert provider.meter == pid


def test_non_registry_quota_meter_is_still_present() -> None:
    # elevenlabs is not a media-registry provider but must remain a known quota meter.
    assert "elevenlabs" in METERS
    assert METERS["elevenlabs"].kind == "quota"
