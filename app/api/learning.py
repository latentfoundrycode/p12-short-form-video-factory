"""Learning API — per-workflow label, rule, and skill counts (PRD §8.5)."""

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.runs import _runs_dir
from app.api.workflows import _holder
from app.core.records import read_video

router = APIRouter(prefix="/api")


class LearningRowOut(BaseModel):
    workflow_id: str
    name: str | None
    label_count: int
    rules_count: int
    skills_count: int
    last_learned: str | None


class LearningListOut(BaseModel):
    workflows: list[LearningRowOut]


def _label_count(runs_dir: Path, workflow_id: str) -> int:
    workflow_runs = runs_dir / workflow_id
    if not workflow_runs.is_dir():
        return 0
    try:
        run_dirs = list(workflow_runs.iterdir())
    except OSError:
        return 0

    count = 0
    for run_dir in run_dirs:
        if not run_dir.is_dir() or not (run_dir / "request.json").is_file():
            continue
        try:
            children = list(run_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or not (child / "video.json").is_file():
                continue
            try:
                record = read_video(child)
            except (OSError, TypeError, ValueError):
                continue
            quality = record.quality
            if isinstance(quality, dict):
                answers = quality.get("answers")
                if isinstance(answers, dict) and answers:
                    count += 1
    return count


def _markdown_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    try:
        return sum(path.is_file() for path in directory.glob("*.md"))
    except OSError:
        return 0


@router.get("/learning", response_model=LearningListOut)
def list_learning(request: Request) -> LearningListOut:
    runs_dir = _runs_dir(request)
    holder = _holder(request)
    entries = holder.snapshot
    return LearningListOut(
        workflows=[
            LearningRowOut(
                workflow_id=entry.folder_name,
                name=None if entry.manifest is None else entry.manifest.workflow.name,
                label_count=_label_count(runs_dir, entry.folder_name),
                rules_count=_markdown_count(entry.path / "rules"),
                skills_count=_markdown_count(entry.path / "skills"),
                last_learned=None,
            )
            for entry in entries
        ]
    )
