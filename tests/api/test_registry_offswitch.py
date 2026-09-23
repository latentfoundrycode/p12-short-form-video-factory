"""Frozen contract — web-image-sourcing increment 6: `RegistryHolder` makes scan-time capability
availability truthful about the paid web tier's RUNTIME prerequisites, so a workflow requiring
`web.images.web` is CAPABILITY_UNAVAILABLE at admission unless the tier is actually usable — rather
than validating, launching, and failing at runtime.

`web.images.web` is offered only when ALL hold:
  * the SerpApi key is configured (`capabilities_offered`), AND
  * the owner has not disabled the `web` tier (DESIGN §5 off-switch), AND
  * the `serpapi` meter has a per-run/per-day budget ceiling (DESIGN §6 — without one every web
    search is refused at `_budget_reserve`).
The keyless, free `commons` tier is unaffected by the off-switch or the budget. Runtime enforcement
lives in media.web / the budget gate; this pins the scan-time half.
"""

from __future__ import annotations

from pathlib import Path

from sfvf.context import BudgetConfig

from app.api.workflows import RegistryHolder


def _serpapi_budget(tmp: Path) -> BudgetConfig:
    # A configured per_day ceiling for the serpapi meter — what DESIGN §6 requires before the web
    # tier is enabled.
    return BudgetConfig(
        ledger_path=tmp / "budget" / "ledger.jsonl", per_day={"serpapi": 1.0}, estimates={}
    )


def test_web_capability_offered_when_key_and_ceiling_present(tmp_path: Path) -> None:
    holder = RegistryHolder(
        tmp_path, configured={"SERPAPI_API_KEY"}, budget=_serpapi_budget(tmp_path)
    )
    offered = holder._offered or frozenset()
    assert "web.images.web" in offered
    assert "web.images.commons" in offered


def test_web_capability_removed_when_the_owner_disables_the_tier(tmp_path: Path) -> None:
    # Key + ceiling present, but the owner disabled the tier => not offered; commons stays.
    holder = RegistryHolder(
        tmp_path,
        configured={"SERPAPI_API_KEY"},
        budget=_serpapi_budget(tmp_path),
        disabled_web_tiers=["web"],
    )
    offered = holder._offered or frozenset()
    assert "web.images.web" not in offered, "a disabled tier must not be offered at scan time"
    assert "web.images.commons" in offered, "commons is unaffected by the web off-switch"


def test_web_capability_needs_a_serpapi_budget_ceiling(tmp_path: Path) -> None:
    # Key present but NO budget => web.images.web is refused at runtime (H21), so it must not be
    # offered at scan time either (DESIGN §6). Commons is free and stays available.
    holder = RegistryHolder(tmp_path, configured={"SERPAPI_API_KEY"}, budget=None)
    offered = holder._offered or frozenset()
    assert "web.images.web" not in offered, "no budget ceiling => web tier not offered"
    assert "web.images.commons" in offered


def test_web_capability_needs_the_serpapi_meter_ceiling_specifically(tmp_path: Path) -> None:
    # A budget with a ceiling for a DIFFERENT meter does not enable the web tier.
    other = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl", per_day={"openai": 1.0}, estimates={}
    )
    holder = RegistryHolder(tmp_path, configured={"SERPAPI_API_KEY"}, budget=other)
    assert "web.images.web" not in (holder._offered or frozenset())


def test_a_per_run_serpapi_ceiling_also_enables_the_web_tier(tmp_path: Path) -> None:
    # Either per_run or per_day suffices (mirrors _budget_reserve's has_ceiling).
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl", per_run={"serpapi": 1.0}, estimates={}
    )
    holder = RegistryHolder(tmp_path, configured={"SERPAPI_API_KEY"}, budget=budget)
    assert "web.images.web" in (holder._offered or frozenset())
