"""Frozen contract — web-image-sourcing increment 1: the capability vocabulary.

Per docs/DESIGN-web-image-sourcing.md §5, web sourcing is gated by TWO capabilities, split by tier
so an owner can permit the keyless licensed/commons tier without the paid, unknown-licence
general-web tier (a single `web.images` would be unconditionally offered because the commons
provider is keyless). This increment only adds the vocabulary; a provider that OFFERS
`web.images.commons` arrives in increment 2, so availability is exercised there.
"""

from __future__ import annotations

from pathlib import Path

from app.registry.problems import ProblemCode
from app.registry.validate import KNOWN_CAPABILITIES, validate
from tests.registry.fixtures import minimal_toml, problem_codes, write_plugin

_UNKNOWN = ProblemCode.CAPABILITY_UNKNOWN.value


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
