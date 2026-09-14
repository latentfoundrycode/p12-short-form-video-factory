"""G-5 contract: the SkillOpt-derived learning ENGINE (Architecture §5.11).

§5.11: "For a chosen workflow: gather every `video.json` containing quality answers since the last
learning run, load that workflow's criteria files with its current rules and skills, and run the
SkillOpt-derived optimiser to propose bounded edits." Three constraints the module ENFORCES:
  * "Only files inside `workflows/<id>/rules/` and `workflows/<id>/skills/` may be modified. Any
    proposal touching a path outside that is rejected outright."
  * "The library is unreachable too … Descriptors … may be read as evidence … but never written."
  * "Proposals are written to a staging area and never applied directly."
  * "On any error, the staging area is discarded and the learning run returns entirely to its state
    before it began, with nothing modified."

This increment is the ENGINE only, with the optimiser LLM call INJECTED as `optimize` (mocked here —
no OpenRouter, no spend). Wiring the real OpenRouter optimiser + a separate learning budget + the
attended first run is a later increment (owner decision 2026-09-14: build mocked first). Acceptance
and archiving are G-6.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.layout import format_video_dir
from app.core.records import VideoRecord, create_request, write_video
from app.learning.engine import (
    LearningError,
    LearningInput,
    ProposedEdit,
    run_learning,
)
from tests.registry.fixtures import minimal_toml, write_plugin

FACTORS = '[[quality_factors]]\nkey = "hook"\nquestion = "Did it hook you?"'


def _workflow(tmp_path: Path) -> Path:
    workflows = tmp_path / "workflows"
    workflows.mkdir(exist_ok=True)
    return write_plugin(
        workflows,
        "explainer",
        minimal_toml("explainer", extra=FACTORS),
        extra_files={
            "criteria/good.md": "A good explainer opens on a concrete object.",
            "rules/tone.md": "---\nagents: [scriptwriter]\nversion: 1\n---\nBe concrete.",
            "skills/composition.md": "# Composition patterns\nUse the safe zone.",
        },
    )


def _seed_labelled_run(tmp_path: Path, workflow_id: str = "explainer") -> Path:
    runs = tmp_path / "runs"
    run_dir = runs / workflow_id / "20260914-100000"
    run_dir.mkdir(parents=True)
    create_request(
        run_dir,
        run_id="20260914-100000",
        workflow={"id": workflow_id, "version": "1.0.0", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "complete"}, {"index": 2, "status": "complete"}],
        status="complete",
    )
    for i, answer in ((1, "great hook"), (2, "weak hook")):
        vdir = run_dir / format_video_dir(i, 2)
        vdir.mkdir(parents=True, exist_ok=True)
        write_video(
            vdir,
            VideoRecord(
                index=i,
                status="complete",
                started_utc="t",
                ended_utc="t",
                quality={"answers": {"hook": answer}, "rankings": {"hook": i}},
            ),
        )
    return runs


def _run(tmp_path: Path, optimize: Any) -> Any:
    workflow_dir = _workflow(tmp_path)
    runs = _seed_labelled_run(tmp_path)
    staging = tmp_path / "staging"
    result = run_learning(workflow_dir, runs_dir=runs, staging_dir=staging, optimize=optimize)
    return result, staging


def test_gathers_labels_and_loads_instructions(tmp_path: Path) -> None:
    captured: dict[str, LearningInput] = {}

    def optimize(inp: LearningInput) -> list[ProposedEdit]:
        captured["input"] = inp
        return []

    result, staging = _run(tmp_path, optimize)
    inp = captured["input"]
    assert inp.workflow_id == "explainer"
    # both answered videos are gathered as labels, with their worded answers
    answers = sorted(label["answers"]["hook"] for label in inp.labels)
    assert answers == ["great hook", "weak hook"]
    # the workflow's criteria + current rules + skills are loaded as evidence
    assert "good.md" in inp.criteria and "concrete object" in inp.criteria["good.md"]
    assert "tone.md" in inp.rules
    assert "composition.md" in inp.skills
    assert result.staged == []
    assert not staging.exists() or not any(staging.rglob("*"))  # nothing staged


def test_stages_valid_rules_and_skills_edits(tmp_path: Path) -> None:
    def optimize(_inp: LearningInput) -> list[ProposedEdit]:
        return [
            ProposedEdit(path="rules/tone.md", content="---\nversion: 2\n---\nOpen on an object."),
            ProposedEdit(path="skills/composition.md", content="# Composition\nNew guidance."),
        ]

    result, staging = _run(tmp_path, optimize)
    assert {e.path for e in result.staged} == {"rules/tone.md", "skills/composition.md"}
    # proposals are written to the STAGING area…
    assert (staging / "rules" / "tone.md").read_text(encoding="utf-8").startswith("---\nversion: 2")
    assert (staging / "skills" / "composition.md").read_text(encoding="utf-8").startswith("# Comp")
    # …and the LIVE workflow files are untouched.
    workflow_dir = tmp_path / "workflows" / "explainer"
    assert "Be concrete." in (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")


def test_rejects_edit_outside_rules_and_skills(tmp_path: Path) -> None:
    # criteria/, the manifest, the library, and any traversal/absolute path are all off-limits.
    # Build the workflow once (write_plugin won't recreate an existing dir) and reject each in turn;
    # run_learning never touches the live workflow, so reuse is safe.
    workflow_dir = _workflow(tmp_path)
    runs = _seed_labelled_run(tmp_path)
    staging = tmp_path / "staging"
    for bad in ("criteria/good.md", "workflow.toml", "../secret.txt", "library/desc.json"):

        def optimize(_inp: LearningInput, _bad: str = bad) -> list[ProposedEdit]:
            return [ProposedEdit(path=_bad, content="x")]

        with pytest.raises(LearningError):
            run_learning(workflow_dir, runs_dir=runs, staging_dir=staging, optimize=optimize)
        assert not staging.exists() or not any(staging.rglob("*"))
    # the live workflow is untouched after all rejections
    assert "Be concrete." in (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")


def test_rejects_backslash_traversal_escape(tmp_path: Path) -> None:
    """Windows escape: a backslash traversal slips past a POSIX-only path check but escapes staging
    when the native Path writes it. Must be rejected, and nothing must land outside staging.

    (Payloads chosen so that, if they DID escape, they land under the pytest tmp dir — never a real
    system path — so running this against an unfixed engine is harmless.)
    """
    workflow_dir = _workflow(tmp_path)
    runs = _seed_labelled_run(tmp_path)
    staging = tmp_path / "staging"
    for bad in (r"rules/..\..\evil.md", r"rules/sub\..\..\..\evil.md"):

        def optimize(_inp: LearningInput, _bad: str = bad) -> list[ProposedEdit]:
            return [ProposedEdit(path=_bad, content="x")]

        with pytest.raises(LearningError):
            run_learning(workflow_dir, runs_dir=runs, staging_dir=staging, optimize=optimize)
    assert not (tmp_path / "evil.md").exists()  # nothing escaped staging


def test_rejects_backslash_and_drive_letter_paths(tmp_path: Path) -> None:
    """Any '\\' or ':' (drive marker) in an edit path is rejected before any write."""
    workflow_dir = _workflow(tmp_path)
    runs = _seed_labelled_run(tmp_path)
    staging = tmp_path / "staging"
    for bad in (r"rules/C:\Windows\evil.md", "rules/x\\y.md", "C:/evil.md", "rules/../evil.md"):

        def optimize(_inp: LearningInput, _bad: str = bad) -> list[ProposedEdit]:
            return [ProposedEdit(path=_bad, content="x")]

        with pytest.raises(LearningError):
            run_learning(workflow_dir, runs_dir=runs, staging_dir=staging, optimize=optimize)


def test_rejects_staging_dir_inside_workflow(tmp_path: Path) -> None:
    """§5.11 ("enforced by the module, not by convention"): a staging_dir that overlaps the
    workflow must be refused BEFORE any rmtree, so a wiring bug can never delete live rules/skills."""
    workflow_dir = _workflow(tmp_path)
    runs = _seed_labelled_run(tmp_path)

    def optimize(_inp: LearningInput) -> list[ProposedEdit]:
        return [ProposedEdit(path="rules/tone.md", content="x")]

    with pytest.raises(LearningError):
        run_learning(
            workflow_dir, runs_dir=runs, staging_dir=workflow_dir / "rules", optimize=optimize
        )
    # the live rules file is untouched (never rmtree'd)
    assert "Be concrete." in (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")


def test_reverts_staging_on_optimize_error(tmp_path: Path) -> None:
    def optimize(_inp: LearningInput) -> list[ProposedEdit]:
        raise RuntimeError("optimiser blew up")

    with pytest.raises(LearningError):
        _run(tmp_path, optimize)
    staging = tmp_path / "staging"
    assert not staging.exists() or not any(staging.rglob("*"))  # staging discarded


def test_rejected_edit_stages_nothing(tmp_path: Path) -> None:
    # A batch with one good and one out-of-scope edit is rejected WHOLE — nothing staged.
    def optimize(_inp: LearningInput) -> list[ProposedEdit]:
        return [
            ProposedEdit(path="rules/tone.md", content="ok"),
            ProposedEdit(path="criteria/good.md", content="nope"),
        ]

    with pytest.raises(LearningError):
        _run(tmp_path, optimize)
    staging = tmp_path / "staging"
    assert not staging.exists() or not any(staging.rglob("*"))
    workflow_dir = tmp_path / "workflows" / "explainer"
    assert "Be concrete." in (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
