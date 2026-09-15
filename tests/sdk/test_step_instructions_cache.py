"""Close the learning loop (cache side): a workflow's applicable instructions (rules/skills) are
part of every step's cache key, so changing a rule INVALIDATES cached step outputs (§5.11).

Without this, `ctx.step` keys on (workflow_version, family, inputs) only; a step cached before a
rule changed would be re-served on the next run, so the injected instructions (agents.llm) never run
the accepted rule has no effect on a rerun with the same inputs. With instructions unchanged the
cache still hits; with no instructions the key is unchanged (existing caches stay valid).
"""

from __future__ import annotations

from pathlib import Path

from sfvf.context import Context, ContextFile, ContextPaths


def _ctx(tmp_path: Path, *, instructions: list[Path]) -> Context:
    video = tmp_path / "01"
    (video / "artifacts").mkdir(parents=True, exist_ok=True)
    (video / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "shared").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            instructions=instructions,
            paths=ContextPaths(
                video=video,
                artifacts=video / "artifacts",
                steps=video / ".steps",
                shared=tmp_path / "shared",
                cache=tmp_path / "cache",  # ONE cache root shared by every ctx below
            ),
            workflow_version="1.0.0",
        )
    )


def _rule(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rules" / "tone.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run_step(ctx: Context) -> bool:
    """Run a fixed step; return whether it was a cache hit."""
    with ctx.step("script", inputs={"topic": "tides"}) as step:
        cached = step.cached
        if not cached:
            step.set({"script": "hello"})
    return cached


def test_same_instructions_hit_changed_instructions_miss(tmp_path: Path) -> None:
    rule = _rule(tmp_path, "Open on a moving object.")
    assert _run_step(_ctx(tmp_path, instructions=[rule])) is False  # first run: miss, stores

    # same instruction content → same key → cache HIT
    assert _run_step(_ctx(tmp_path, instructions=[rule])) is True

    # change the rule's CONTENT → key changes → cache MISS (so the new rule can take effect)
    rule.write_text("Open on a question.", encoding="utf-8")
    assert _run_step(_ctx(tmp_path, instructions=[rule])) is False


def test_no_instructions_preserves_the_prior_cache_key(tmp_path: Path) -> None:
    # A workflow with no rules/skills keys exactly as before, so existing caches stay valid.
    assert _run_step(_ctx(tmp_path, instructions=[])) is False  # miss, stores
    assert _run_step(_ctx(tmp_path, instructions=[])) is True  # hit — key unchanged by the feature
