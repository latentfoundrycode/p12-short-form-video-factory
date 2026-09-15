"""Learning API — per-workflow label, rule, and skill counts (PRD §8.5)."""

import logging
import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sfvf.context import BudgetConfig

from app.api.runs import _runs_dir, _secrets
from app.api.workflows import _holder
from app.core import ids
from app.core.records import read_request, read_video
from app.core.supervisor import _redact_secrets
from app.learning.accept import AcceptError, accept_learning, reject_learning
from app.learning.completion import make_openrouter_completion
from app.learning.engine import LearningError, OptimizeFn, ProposedEdit, run_learning
from app.learning.optimizer import make_optimizer
from app.learning.state import read_last_learned, write_last_learned
from app.paths import is_safe_path_segment
from app.registry.validate import WorkflowEntry

router = APIRouter(prefix="/api")

_log = logging.getLogger("app.api.learning")
_WORKFLOW_LOCKS: dict[str, threading.Lock] = {}
_WORKFLOW_LOCKS_GUARD = threading.Lock()


def _workflow_lock(workflow_id: str) -> threading.Lock:
    with _WORKFLOW_LOCKS_GUARD:
        lock = _WORKFLOW_LOCKS.get(workflow_id)
        if lock is None:
            lock = threading.Lock()
            _WORKFLOW_LOCKS[workflow_id] = lock
        return lock


LEARNING_MODEL = "openai/gpt-4o-mini"
type MakeLearningOptimizer = Callable[[str, str], OptimizeFn]


def make_default_learning_optimizer(
    secrets: Mapping[str, str], budget: BudgetConfig | None
) -> MakeLearningOptimizer:
    def factory(workflow_id: str, run_id: str) -> OptimizeFn:
        return make_optimizer(
            make_openrouter_completion(
                secrets=secrets,
                budget=budget,
                model=LEARNING_MODEL,
                run_id=run_id,
            )
        )

    return factory


class LearningRowOut(BaseModel):
    workflow_id: str
    name: str | None
    label_count: int
    rules_count: int
    skills_count: int
    last_learned: str | None


class LearningListOut(BaseModel):
    workflows: list[LearningRowOut]


class StagedProposalOut(BaseModel):
    path: str
    content: str


class StagedOut(BaseModel):
    staged: list[StagedProposalOut]


class AcceptOut(BaseModel):
    applied: list[str]


def _entry(request: Request, workflow_id: str) -> WorkflowEntry:
    if not is_safe_path_segment(workflow_id):
        raise HTTPException(status_code=404)
    entry = _holder(request).get(workflow_id)
    if entry is None:
        raise HTTPException(status_code=404)
    return entry


def _staging_for(request: Request, workflow_id: str) -> Path:
    staging_dir = cast(Path, request.app.state.learning_staging_dir)
    return staging_dir / workflow_id


def _learning_state_dir(request: Request) -> Path:
    return cast(Path, request.app.state.learning_state_dir)


def _read_staged(staging: Path) -> list[StagedProposalOut]:
    return [
        StagedProposalOut(
            path=path.relative_to(staging).as_posix(),
            content=path.read_text(encoding="utf-8"),
        )
        for path in sorted(staging.rglob("*"))
        if path.is_file()
    ]


def _label_count(runs_dir: Path, workflow_id: str, since: str | None = None) -> int:
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
            request = read_request(run_dir)
            children = list(run_dir.iterdir())
        except (OSError, TypeError, ValueError):
            continue
        if since is not None and not (request.started_utc > since):
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
    state_dir = _learning_state_dir(request)
    rows: list[LearningRowOut] = []
    for entry in entries:
        marker = read_last_learned(state_dir, entry.folder_name)
        rows.append(
            LearningRowOut(
                workflow_id=entry.folder_name,
                name=None if entry.manifest is None else entry.manifest.workflow.name,
                label_count=_label_count(runs_dir, entry.folder_name, since=marker),
                rules_count=_markdown_count(entry.path / "rules"),
                skills_count=_markdown_count(entry.path / "skills"),
                last_learned=marker,
            )
        )
    return LearningListOut(workflows=rows)


@router.post("/learning/{workflow_id}/run", response_model=StagedOut)
def run_learning_for_workflow(request: Request, workflow_id: str) -> StagedOut:
    entry = _entry(request, workflow_id)
    with _workflow_lock(workflow_id):
        staging = _staging_for(request, workflow_id)
        run_id = f"learning-{workflow_id}-{uuid.uuid4().hex}"
        optimize = request.app.state.make_learning_optimizer(workflow_id, run_id)
        since = read_last_learned(_learning_state_dir(request), workflow_id)
        try:
            result = run_learning(
                entry.path,
                runs_dir=_runs_dir(request),
                staging_dir=staging,
                optimize=optimize,
                since=since,
            )
        except LearningError as exc:
            secret_values = frozenset(v for v in _secrets(request).values() if v)
            cause = _redact_secrets(repr(exc.__cause__ or exc), secret_values)
            _log.warning("learning run failed for %s: %s", workflow_id, cause)
            raise HTTPException(status_code=502, detail="learning run failed") from exc
        staged: list[ProposedEdit] = result.staged
        return StagedOut(
            staged=[StagedProposalOut(path=edit.path, content=edit.content) for edit in staged]
        )


@router.get("/learning/{workflow_id}/staged", response_model=StagedOut)
def get_staged_learning(request: Request, workflow_id: str) -> StagedOut:
    _entry(request, workflow_id)
    return StagedOut(staged=_read_staged(_staging_for(request, workflow_id)))


@router.post("/learning/{workflow_id}/accept", response_model=AcceptOut)
def accept_staged_learning(request: Request, workflow_id: str) -> AcceptOut:
    entry = _entry(request, workflow_id)
    with _workflow_lock(workflow_id):
        try:
            result = accept_learning(entry.path, _staging_for(request, workflow_id))
        except AcceptError as exc:
            raise HTTPException(
                status_code=502, detail="could not apply learning proposals"
            ) from exc
        if result.applied:
            write_last_learned(
                _learning_state_dir(request),
                workflow_id,
                ids.format_utc_z(ids.utc_now()),
            )
        return AcceptOut(applied=result.applied)


@router.post("/learning/{workflow_id}/reject")
def reject_staged_learning(request: Request, workflow_id: str) -> dict[str, bool]:
    _entry(request, workflow_id)
    with _workflow_lock(workflow_id):
        reject_learning(_staging_for(request, workflow_id))
        return {"ok": True}
