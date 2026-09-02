"""A-3 contract: `sfvf.agents` language-model / research stubs (SDK §6.1).

`agents.llm` and `agents.research` are called without `ctx`; they read the ambient
Context (A-1) to decide dry-run. In dry-run they return deterministic free stubs so a
workflow's structure can be exercised for nothing (SDK §10). The real OpenRouter adapter
arrives in Stage B, so the non-dry path raises rather than silently doing nothing.

Provided-function results must be JSON-serializable, because the documented pattern caches
them via `ctx.step` and step results are JSON (SDK §5.5). So `Source` is a TypedDict (a
plain dict at runtime) rather than a rich object, and `research()` returns JSON-native data.
"""

import json
from pathlib import Path

import pytest
from sfvf import Source, agents
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths


def _ctx(video_dir: Path, *, dry_run: bool) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            paths=ContextPaths(
                video=video_dir,
                artifacts=video_dir / "artifacts",
                steps=video_dir / ".steps",
                shared=video_dir,
            ),
        )
    )


def test_llm_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        agents.llm("hi", agent="a", model="m")


def test_research_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        agents.research("hi")


def test_llm_dry_run_returns_deterministic_text(tmp_path: Path) -> None:
    token = set_active(_ctx(tmp_path, dry_run=True))
    try:
        first = agents.llm("write a script", agent="scriptwriter", model="gpt-x")
        second = agents.llm("write a script", agent="scriptwriter", model="gpt-x")
    finally:
        reset_active(token)
    assert isinstance(first, str)
    assert first  # non-empty
    assert first == second  # deterministic in the inputs


def test_llm_dry_run_with_schema_returns_matching_dict(tmp_path: Path) -> None:
    # A structured-output stub must reflect the requested schema so a workflow that
    # reads schema fields can be exercised in dry-run (not just get a generic blob).
    schema = {
        "type": "object",
        "properties": {
            "logline": {"type": "string"},
            "beats": {"type": "array"},
            "shots": {"type": "integer"},
        },
    }
    token = set_active(_ctx(tmp_path, dry_run=True))
    try:
        out = agents.llm("give me json", agent="a", model="m", schema=schema)
        again = agents.llm("give me json", agent="a", model="m", schema=schema)
    finally:
        reset_active(token)
    assert isinstance(out, dict)
    assert set(out) == {"logline", "beats", "shots"}
    assert isinstance(out["logline"], str)
    assert isinstance(out["beats"], list)
    assert isinstance(out["shots"], int)
    assert out == again  # deterministic
    json.dumps(out)  # JSON-serializable


def test_research_dry_run_returns_json_native_sources(tmp_path: Path) -> None:
    token = set_active(_ctx(tmp_path, dry_run=True))
    try:
        first = agents.research("krebs cycle")
        second = agents.research("krebs cycle")
    finally:
        reset_active(token)
    assert isinstance(first, list)
    assert first  # non-empty
    # Source is a TypedDict — plain dicts at runtime, so results cache via ctx.step.
    assert set(Source.__annotations__) == {"title", "url", "snippet"}
    for s in first:
        assert isinstance(s, dict)
        assert isinstance(s["title"], str)
        assert isinstance(s["url"], str)
        assert isinstance(s["snippet"], str)
    assert first == second  # deterministic in the query
    json.dumps(first)  # JSON-serializable (SDK §5.5) — must not raise


def test_llm_non_dry_run_raises_not_implemented(tmp_path: Path) -> None:
    token = set_active(_ctx(tmp_path, dry_run=False))
    try:
        with pytest.raises(NotImplementedError):
            agents.llm("x", agent="a", model="m")
    finally:
        reset_active(token)


def test_research_non_dry_run_raises_not_implemented(tmp_path: Path) -> None:
    token = set_active(_ctx(tmp_path, dry_run=False))
    try:
        with pytest.raises(NotImplementedError):
            agents.research("x")
    finally:
        reset_active(token)
