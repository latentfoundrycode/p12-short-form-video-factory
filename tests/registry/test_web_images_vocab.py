"""Frozen contract — web-image-sourcing increment 1: the capability vocabulary.

Per docs/DESIGN-web-image-sourcing.md §5, web sourcing is gated by TWO capabilities, split by tier
so an owner can permit the keyless licensed/commons tier without the paid, unknown-licence
general-web tier (a single `web.images` would be unconditionally offered because the commons
provider is keyless). This increment only adds the vocabulary; a provider that OFFERS
`web.images.commons` arrives in increment 2, so availability is exercised there.
"""

from __future__ import annotations

from pathlib import Path

from sfvf.providers import capabilities_offered, providers_offering

from app.registry.problems import ProblemCode
from app.registry.validate import KNOWN_CAPABILITIES, validate
from tests.registry.fixtures import minimal_toml, problem_codes, write_plugin

_UNKNOWN = ProblemCode.CAPABILITY_UNKNOWN.value
_UNAVAIL = ProblemCode.CAPABILITY_UNAVAILABLE.value


def test_web_image_capabilities_are_known_vocabulary() -> None:
    assert "web.images.commons" in KNOWN_CAPABILITIES
    assert "web.images.web" in KNOWN_CAPABILITIES


def test_requiring_a_web_image_capability_is_not_a_vocabulary_error(tmp_path: Path) -> None:
    # A workflow may declare either tier without CAPABILITY_UNKNOWN. (offered=None skips the
    # availability check, which belongs to increment 2 once a provider offers the capability.)
    # Distinct folder per case so write_plugin does not re-create the same directory.
    for i, cap in enumerate(("web.images.commons", "web.images.web")):
        toml = minimal_toml(extra=f'requires_capabilities = ["{cap}"]')
        plugin = write_plugin(tmp_path, f"photo-explainer-{i}", toml)
        entry = validate(plugin)
        assert _UNKNOWN not in problem_codes(entry), f"{cap} should be known vocabulary"


def test_commons_tier_is_offered_keylessly_but_web_tier_is_not() -> None:
    # Increment 2 registers the keyless Openverse provider for the licensed/commons tier, so
    # web.images.commons is offered (by "Openverse") with NO key configured. The general-web tier
    # has no provider yet, so web.images.web stays unoffered.
    assert providers_offering("web.images.commons") == ["Openverse"]
    assert providers_offering("web.images.web") == []
    # keyless => offered even against an empty configured set; web tier absent.
    offered = capabilities_offered(set())
    assert "web.images.commons" in offered
    assert "web.images.web" not in offered


def test_availability_reflects_the_commons_flip(tmp_path: Path) -> None:
    # A workflow requiring web.images.commons now validates (available); web.images.web is still
    # CAPABILITY_UNAVAILABLE until its paid provider is registered (increment 6).
    offered = capabilities_offered(set())
    commons = write_plugin(
        tmp_path,
        "commons-wf",
        minimal_toml(extra='requires_capabilities = ["web.images.commons"]'),
    )
    assert _UNAVAIL not in problem_codes(validate(commons, offered=offered))
    web = write_plugin(
        tmp_path,
        "web-wf",
        minimal_toml(extra='requires_capabilities = ["web.images.web"]'),
    )
    assert _UNAVAIL in problem_codes(validate(web, offered=offered))
