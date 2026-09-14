from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.records import read_request, read_video


class LearningError(Exception):
    """Raised when a learning run cannot be completed."""


@dataclass(frozen=True)
class ProposedEdit:
    path: str
    content: str


@dataclass(frozen=True)
class LearningInput:
    workflow_id: str
    labels: list[dict[str, Any]]
    criteria: dict[str, str]
    rules: dict[str, str]
    skills: dict[str, str]


@dataclass(frozen=True)
class LearningResult:
    staged: list[ProposedEdit]


type OptimizeFn = Callable[[LearningInput], list[ProposedEdit]]


def _gather_labels(runs_dir: Path, workflow_id: str) -> list[dict[str, Any]]:
    workflow_runs = runs_dir / workflow_id
    if not workflow_runs.is_dir():
        return []
    try:
        run_dirs = sorted(workflow_runs.iterdir())
    except OSError:
        return []

    labels: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        if not run_dir.is_dir() or not (run_dir / "request.json").is_file():
            continue
        try:
            read_request(run_dir)
            children = sorted(run_dir.iterdir())
        except (OSError, TypeError, ValueError):
            continue
        for child in children:
            if not child.is_dir() or not (child / "video.json").is_file():
                continue
            try:
                record = read_video(child)
            except (OSError, TypeError, ValueError):
                continue
            quality = record.quality
            if not isinstance(quality, dict):
                continue
            answers = quality.get("answers")
            if not isinstance(answers, dict) or not answers:
                continue
            labels.append(
                {
                    "run_id": run_dir.name,
                    "video_index": record.index,
                    "answers": answers,
                    "rankings": quality.get("rankings") or {},
                    "accepted": quality.get("accepted"),
                }
            )
    return labels


def _load_markdown(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(directory.glob("*.md"))
        if path.is_file()
    }


def _validate_edits(edits: list[ProposedEdit]) -> None:
    for edit in edits:
        if "\\" in edit.path or ":" in edit.path:
            raise LearningError(f"edit path is outside rules/ and skills/: {edit.path}")
        path = PurePosixPath(edit.path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) < 2
            or path.parts[0] not in {"rules", "skills"}
        ):
            raise LearningError(f"edit path is outside rules/ and skills/: {edit.path}")


def run_learning(
    workflow_dir: Path,
    *,
    runs_dir: Path,
    staging_dir: Path,
    optimize: OptimizeFn,
) -> LearningResult:
    workflow_resolved = workflow_dir.resolve()
    staging_resolved = staging_dir.resolve()
    if (
        staging_resolved == workflow_resolved
        or workflow_resolved in staging_resolved.parents
        or staging_resolved in workflow_resolved.parents
    ):
        raise LearningError(
            f"staging_dir must be disjoint from the workflow directory: {staging_dir}"
        )

    workflow_id = workflow_dir.name
    try:
        learning_input = LearningInput(
            workflow_id=workflow_id,
            labels=_gather_labels(runs_dir, workflow_id),
            criteria=_load_markdown(workflow_dir / "criteria"),
            rules=_load_markdown(workflow_dir / "rules"),
            skills=_load_markdown(workflow_dir / "skills"),
        )
        edits = optimize(learning_input)
        _validate_edits(edits)

        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True)
        for edit in edits:
            destination = staging_dir.joinpath(*PurePosixPath(edit.path).parts)
            if not destination.resolve().is_relative_to(staging_dir.resolve()):
                raise LearningError(f"edit path escapes the staging area: {edit.path}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(edit.content, encoding="utf-8", newline="\n")
        return LearningResult(staged=list(edits))
    except LearningError:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise LearningError("learning run failed") from exc
