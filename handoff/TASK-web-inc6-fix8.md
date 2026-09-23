# TASK — web-image-sourcing inc6 FIX round 8: gate the web capability on a budget ceiling (DESIGN §6)

## Why this round
Cross-family review (P2): `web.images.web` is advertised as offered whenever the SerpApi key is
present, but `DESIGN §6` requires the web-tier meter to have a per-run/per-day **ceiling** before the
tier is enabled ("increment 6 adds a validation/startup check that the web meter has a ceiling before
the tier is enabled"). Without a ceiling, `ctx._budget_reserve("serpapi", ...)` refuses every web
search at runtime (H21 fail-closed), so a dependent workflow validates and launches, then fails on the
first search. It should be `CAPABILITY_UNAVAILABLE` at admission instead — the same "advertise-then-
fail" gap the round-7 off-switch fix closed, now for the budget prerequisite.

After this, `web.images.web` is offered iff: key configured AND not disabled by the owner AND the
`serpapi` meter has a budget ceiling. The free, keyless `commons` tier is unaffected.

A frozen RED contract is committed (HEAD): `tests/api/test_registry_offswitch.py` (now also covers the
budget cases).

## Change (one file) — `app/api/workflows.py`
`RegistryHolder.__init__` gains the run's budget config and removes `web.images.web` from the offered
set when the `serpapi` meter has no ceiling. Keep the round-7 off-switch subtraction:
```python
    def __init__(
        self,
        workflows_dir: Path,
        *,
        configured: set[str] | None = None,
        disabled_web_tiers: list[str] | None = None,
        budget: BudgetConfig | None = None,
    ) -> None:
        self.workflows_dir = workflows_dir
        offered = None if configured is None else capabilities_offered(set(configured))
        if offered is not None:
            if disabled_web_tiers:
                offered = offered - {f"web.images.{tier}" for tier in disabled_web_tiers}
            # DESIGN §6: the paid web tier needs a configured ceiling for its meter; without one every
            # web search is refused at runtime, so the capability must not be offered.
            if "web.images.web" in offered and not _serpapi_has_ceiling(budget):
                offered = offered - {"web.images.web"}
        self._offered: frozenset[str] | None = offered
        self.snapshot: list[WorkflowEntry] = scan(workflows_dir, offered=self._offered)
```
Add a module-level helper (mirrors `_budget_reserve`'s `has_ceiling` check):
```python
def _serpapi_has_ceiling(budget: BudgetConfig | None) -> bool:
    return budget is not None and ("serpapi" in budget.per_run or "serpapi" in budget.per_day)
```
Import `BudgetConfig` from `sfvf.context`. (The meter name for the SerpApi provider is `"serpapi"` —
`PROVIDERS["serpapi"].meter`; hardcoding the string is fine and matches the design's specificity.)

## Wire the budget in — `app/main.py`
Pass the run's budget config to the single `RegistryHolder(...)` construction (~line 102), the same
`application.state.budget` the run paths use. That state is currently assigned AFTER the construction
(`application.state.budget = budget if budget is not None else load_budget_config()`); move that
assignment ABOVE the `RegistryHolder(...)` call (as was done for `disabled_web_tiers`), then pass
`budget=application.state.budget`. Exactly one assignment to `application.state.budget`; no duplicate.
Default stays `None`, so with no budget the web tier is simply not offered (correct per §6).

## Scope
Only `app/api/workflows.py` and `app/main.py`. Do NOT change the SDK, media.web, `capabilities_offered`
(keep it pure — gate in the app holder), the serpapi adapter, the registry vocabulary, or the frozen
tests. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/api/test_registry_offswitch.py -q` → all 5 pass.
- Broader app suite via the project venv (subprocess tests need `sfvf` installed):
  `.\.venv\Scripts\python.exe -m pytest tests/api tests/registry tests/core -q` → all pass. Watch for
  any existing test that constructs the app/registry expecting `web.images.web` offered without a
  budget — if one breaks, it was relying on the pre-§6 behaviour; report it rather than editing a
  frozen test.
- `ruff check .` and `ruff format --check .` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
