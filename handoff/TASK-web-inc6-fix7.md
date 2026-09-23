# TASK — web-image-sourcing inc6 FIX round 7: gate scan-time capability availability on the off-switch

## Why this round
Cross-family review (P2): the runtime web-tier off-switch (DESIGN §5, already implemented) is ignored
during **capability scanning**. `RegistryHolder` derives offered capabilities from configured secrets
only, so with `SFVF_DISABLE_WEB_TIERS=web` the capability `web.images.web` is still advertised as
offered — a workflow that requires it validates and launches, then fails only at runtime with
`WebTierDisabledError`. It should be marked **CAPABILITY_UNAVAILABLE at admission** instead.

Runtime enforcement (the design's mandated safety control) stays as-is; this closes the scan-time
consistency gap so a disabled tier is unavailable at admission AND refused at runtime.

A frozen RED contract is committed (HEAD): `tests/api/test_registry_offswitch.py`.

## Change (one file)
`app/api/workflows.py` — `RegistryHolder.__init__` takes the owner's disabled web-image tiers and
removes each disabled tier's capability from the offered set. Tier → capability is `web.images.<tier>`
(the design's split-by-tier vocabulary: `web`→`web.images.web`, `commons`→`web.images.commons`):
```python
    def __init__(
        self,
        workflows_dir: Path,
        *,
        configured: set[str] | None = None,
        disabled_web_tiers: list[str] | None = None,
    ) -> None:
        self.workflows_dir = workflows_dir
        offered = None if configured is None else capabilities_offered(set(configured))
        if offered is not None and disabled_web_tiers:
            offered = offered - {f"web.images.{tier}" for tier in disabled_web_tiers}
        self._offered: frozenset[str] | None = offered
        self.snapshot: list[WorkflowEntry] = scan(workflows_dir, offered=self._offered)
```
(Subtracting `web.images.<tier>` for an unknown/typo tier is a harmless no-op — it isn't in the set.)

## Wire the value in at construction — `app/main.py`
`RegistryHolder` is constructed once (~line 102) as
`RegistryHolder(workflows_dir or WORKFLOWS_DIR, configured=set(resolved))`. Pass the same owner
setting the run paths already use:
```python
    application.state.registry = RegistryHolder(
        workflows_dir or WORKFLOWS_DIR,
        configured=set(resolved),
        disabled_web_tiers=application.state.disabled_web_tiers,
    )
```
Ensure `application.state.disabled_web_tiers = load_disabled_web_tiers()` is set BEFORE the
`RegistryHolder(...)` construction (reorder if the assignment currently comes after it, or call
`load_disabled_web_tiers()` directly in the `RegistryHolder(...)` call). Default stays `[]` (nothing
disabled), so behaviour is unchanged unless the owner sets the env var.

## Scope
Only `app/api/workflows.py` and `app/main.py`. Do NOT change the SDK, the media.web runtime
enforcement, `capabilities_offered` (keep it pure — do the subtraction in the app holder), the serpapi
adapter, the registry vocabulary, or the frozen tests. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/api/test_registry_offswitch.py -q` → both pass.
- Run the broader app suite through the project venv (subprocess-spawning tests need `sfvf` installed):
  `.\.venv\Scripts\python.exe -m pytest tests/api tests/registry tests/core -q` → all pass (no
  regression to registry scan / availability / admission).
- `ruff check .` and `ruff format --check .` clean; `.\.venv\Scripts\python.exe -m mypy` clean if it
  runs in your env.
