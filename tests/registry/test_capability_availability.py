"""Frozen contract — Stage P, P-8b: CAPABILITY_UNAVAILABLE at scan.

Today the registry scan only checks that each `requires_capabilities` entry is a KNOWN capability
name (`CAPABILITY_UNKNOWN`). P-8b adds a second check: a known capability that no CONFIGURED
provider offers is a `CAPABILITY_UNAVAILABLE` error (the blocked badge), whose message names the
capability and which providers would offer it.

Threading: `RegistryHolder(configured=<secret names>)` computes what is offered
(`capabilities_offered`) and passes it into `scan(..., offered=)` -> `validate(..., offered=)`. When
`offered` is None (the default for a bare `validate`/`scan`/holder call), the availability check is
SKIPPED — so every pre-existing direct `validate(folder)` caller is unaffected; only a caller that
supplies the configured set opts into the availability check.

Acceptance (plan §P-8): `agents.structured` is offered once OpenRouter is configured (a
provider-level capability); `agents.vision` is a known capability that NO provider offers yet, so
it is always unavailable — even with OpenRouter configured — until vision attachments are built.
"""

from __future__ import annotations

from pathlib import Path

from sfvf.providers import capabilities_offered, providers_offering

from app.api.workflows import RegistryHolder
from app.registry.problems import ProblemCode
from app.registry.scan import scan
from app.registry.validate import validate
from tests.registry.fixtures import minimal_toml, problem_codes, write_plugin

_UNAVAIL = ProblemCode.CAPABILITY_UNAVAILABLE.value
_UNKNOWN = ProblemCode.CAPABILITY_UNKNOWN.value


def _wf(tmp: Path, caps: str) -> Path:
    toml = minimal_toml(extra=f"requires_capabilities = [{caps}]")
    return write_plugin(tmp, "news-explainer", toml)


# ---------------------------------------------------------------------------
# providers_offering (SDK primitive for the message)
# ---------------------------------------------------------------------------


def test_providers_offering_lists_labels_of_providers_with_a_capability() -> None:
    # agents.structured is a provider-level capability on OpenRouter.
    structured = providers_offering("agents.structured")
    assert "OpenRouter" in structured
    # video.generate is offered by the seeded video models' providers.
    assert providers_offering("video.generate")  # non-empty
    # agents.vision is known vocabulary but no provider/model offers it yet.
    assert providers_offering("agents.vision") == []


# ---------------------------------------------------------------------------
# validate(offered=...) semantics
# ---------------------------------------------------------------------------


def test_offered_none_skips_the_availability_check(tmp_path: Path) -> None:
    entry = validate(_wf(tmp_path, '"video.generate"'))  # offered defaults to None
    assert _UNAVAIL not in problem_codes(entry)
    assert _UNKNOWN not in problem_codes(entry)


def test_declared_capability_that_is_offered_is_ok(tmp_path: Path) -> None:
    entry = validate(_wf(tmp_path, '"video.generate"'), offered=frozenset({"video.generate"}))
    assert _UNAVAIL not in problem_codes(entry)


def test_declared_known_capability_not_offered_is_unavailable(tmp_path: Path) -> None:
    entry = validate(_wf(tmp_path, '"video.generate"'), offered=frozenset())
    assert _UNAVAIL in problem_codes(entry)
    unavailable = [p for p in entry.problems if p.code == ProblemCode.CAPABILITY_UNAVAILABLE]
    assert unavailable and unavailable[0].severity == "error"
    assert "video.generate" in unavailable[0].message


def test_unknown_capability_is_unknown_not_unavailable(tmp_path: Path) -> None:
    # An unknown name is a vocabulary error; the availability check does not also fire for it.
    entry = validate(_wf(tmp_path, '"telepathy"'), offered=frozenset())
    codes = problem_codes(entry)
    assert _UNKNOWN in codes
    assert not any(
        p.code == ProblemCode.CAPABILITY_UNAVAILABLE and "telepathy" in p.message
        for p in entry.problems
    )


# ---------------------------------------------------------------------------
# scan(offered=...) threads the check
# ---------------------------------------------------------------------------


def test_scan_threads_offered(tmp_path: Path) -> None:
    _wf(tmp_path, '"video.generate"')
    without = scan(tmp_path)  # offered=None -> no availability check
    assert _UNAVAIL not in problem_codes(without[0])
    blocked = scan(tmp_path, offered=frozenset())
    assert _UNAVAIL in problem_codes(blocked[0])


# ---------------------------------------------------------------------------
# RegistryHolder(configured=...) end-to-end + the acceptance cases
# ---------------------------------------------------------------------------


def test_holder_without_configured_skips_the_check(tmp_path: Path) -> None:
    _wf(tmp_path, '"agents.vision"')
    holder = RegistryHolder(tmp_path)  # configured omitted -> offered None -> skip
    assert _UNAVAIL not in problem_codes(holder.snapshot[0])


def test_agents_structured_is_ok_when_openrouter_configured(tmp_path: Path) -> None:
    _wf(tmp_path, '"agents.structured"')
    holder = RegistryHolder(tmp_path, configured={"OPENROUTER_API_KEY"})
    assert _UNAVAIL not in problem_codes(holder.snapshot[0])


def test_agents_vision_is_unavailable_even_with_openrouter_configured(tmp_path: Path) -> None:
    _wf(tmp_path, '"agents.vision"')
    holder = RegistryHolder(tmp_path, configured={"OPENROUTER_API_KEY"})
    assert _UNAVAIL in problem_codes(holder.snapshot[0])


def test_configured_offered_matches_capabilities_offered(tmp_path: Path) -> None:
    # A capability offered only once its provider's key is configured.
    _wf(tmp_path, '"agents.structured"')
    offered_without = capabilities_offered(set())
    assert "agents.structured" not in offered_without
    holder = RegistryHolder(tmp_path, configured=set())
    assert _UNAVAIL in problem_codes(holder.snapshot[0])
