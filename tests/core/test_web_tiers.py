"""Frozen contract — web-image-sourcing increment 6: the runtime web-tier governance off-switch
activation layer (DESIGN §5).

Mirrors the budget activation layer (`app/core/budget_config.py`): the owner disables web-image
tiers via an env-gated setting that the supervisor reads and injects into each run's context, so
the SDK re-checks it before any paid dispatch. `SFVF_DISABLE_WEB_TIERS` is a comma-separated list of
tier names (e.g. "web"); unset/empty means nothing disabled (design default: enabled with the key).
Parsing is lenient: whitespace trimmed, blanks dropped, lowercased, de-duplicated, order preserved.
"""

from __future__ import annotations

import pytest

from app.core.web_tiers import load_disabled_web_tiers


def test_unset_means_nothing_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SFVF_DISABLE_WEB_TIERS", raising=False)
    assert load_disabled_web_tiers() == []


def test_blank_value_means_nothing_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFVF_DISABLE_WEB_TIERS", "   ,  ")
    assert load_disabled_web_tiers() == []


def test_single_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFVF_DISABLE_WEB_TIERS", "web")
    assert load_disabled_web_tiers() == ["web"]


def test_multiple_tiers_are_trimmed_lowercased_and_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SFVF_DISABLE_WEB_TIERS", " Web , commons ,web")
    assert load_disabled_web_tiers() == ["web", "commons"]
