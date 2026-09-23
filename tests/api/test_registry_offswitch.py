"""Frozen contract — web-image-sourcing increment 6: the web-tier off-switch also gates SCAN-time
capability availability (DESIGN §5), so a workflow requiring a disabled tier is marked unavailable
at admission rather than validating, launching, and failing only at runtime.

The runtime enforcement lives in media.web (test_media_web_web.py); this pins the scan-time half:
`RegistryHolder` removes a disabled web-image tier's capability from the offered set. The tier ->
capability mapping is `web.images.<tier>` (the design's split-by-tier vocabulary).
"""

from __future__ import annotations

from pathlib import Path

from app.api.workflows import RegistryHolder


def test_registry_removes_a_disabled_web_tier_capability_from_offered(tmp_path: Path) -> None:
    # Key configured => web.images.web is offered, and commons is always offered (keyless).
    holder_on = RegistryHolder(tmp_path, configured={"SERPAPI_API_KEY"})
    offered_on = holder_on._offered or frozenset()
    assert "web.images.web" in offered_on
    assert "web.images.commons" in offered_on

    # Owner disables the web tier => its capability must NOT be offered at scan time; commons stays.
    holder_off = RegistryHolder(
        tmp_path, configured={"SERPAPI_API_KEY"}, disabled_web_tiers=["web"]
    )
    offered_off = holder_off._offered or frozenset()
    assert "web.images.web" not in offered_off, "a disabled tier must not be offered at scan time"
    assert "web.images.commons" in offered_off, "commons is unaffected by the web off-switch"


def test_registry_off_switch_defaults_to_nothing_disabled(tmp_path: Path) -> None:
    # No disabled tiers (the default) leaves the key-based availability unchanged.
    holder = RegistryHolder(tmp_path, configured={"SERPAPI_API_KEY"}, disabled_web_tiers=[])
    assert "web.images.web" in (holder._offered or frozenset())
