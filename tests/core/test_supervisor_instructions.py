"""Close the learning loop (supervisor side): the chassis loads a workflow's rules/*.md and
skills/*.md into `ctx.instructions` so they reach generation (§5.11). `agents.llm` then injects
their content into every LLM prompt (see tests/integration/test_agents_instructions.py).

`instruction_paths(workflow_dir)` returns the rule and skill markdown paths that apply to a run,
rules before skills and sorted within each, so the injected instruction block is stable and ordered.
"""

from __future__ import annotations

from pathlib import Path

from app.core.supervisor import instruction_paths


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_globs_rules_then_skills_sorted(tmp_path: Path) -> None:
    wf = tmp_path / "workflows" / "explainer"
    _write(wf / "rules" / "tone.md")
    _write(wf / "rules" / "aaa.md")
    _write(wf / "skills" / "hooks.md")
    _write(wf / "criteria" / "criteria.md")  # criteria are NOT instructions
    _write(wf / "workflow.toml")  # non-md, ignored

    paths = instruction_paths(wf)

    rels = [p.relative_to(wf).as_posix() for p in paths]
    assert rels == ["rules/aaa.md", "rules/tone.md", "skills/hooks.md"]  # rules→skills, sorted
    assert all(p.is_absolute() for p in paths)  # readable by the child process


def test_empty_when_no_rules_or_skills(tmp_path: Path) -> None:
    wf = tmp_path / "workflows" / "bare"
    _write(wf / "workflow.toml")
    assert instruction_paths(wf) == []


def test_missing_directory_is_empty(tmp_path: Path) -> None:
    assert instruction_paths(tmp_path / "does-not-exist") == []
