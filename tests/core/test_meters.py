"""Contract: the meter registry classifies meters for display (PRD §7.1).

Fiat meters are the only ones ever summed together; credit meters each stand alone; an unknown meter
falls back to a standalone credit line (never merged into the fiat total) so an unrecognised unit is
never added to anything else.
"""

from __future__ import annotations

from app.core.meters import METERS, MeterInfo, meter_info


def test_known_fiat_meter() -> None:
    info = meter_info("openrouter")
    assert info.kind == "fiat"
    assert info.provider == "OpenRouter"
    assert info.unit == "usd"


def test_known_credit_meter() -> None:
    info = meter_info("higgsfield")
    assert info.kind == "credit"
    assert info.provider == "Higgsfield"
    assert info.unit == "credits"


def test_unknown_meter_is_standalone_credit_labelled_by_id() -> None:
    # An unknown meter must never be folded into fiat: it becomes its own credit line named by id.
    info = meter_info("someprovider")
    assert info.kind == "credit"
    assert info.provider == "someprovider"


def test_custom_registry_is_honoured() -> None:
    reg = {"foo": MeterInfo(kind="fiat", provider="Foo", unit="usd")}
    assert meter_info("foo", reg).provider == "Foo"
    # A meter absent from the custom registry still falls back to standalone credit.
    assert meter_info("higgsfield", reg).kind == "credit"


def test_default_registry_has_the_live_providers() -> None:
    assert METERS["openrouter"].kind == "fiat"
    assert METERS["higgsfield"].kind == "credit"
