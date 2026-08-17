import mimetypes
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.paths import is_safe_path_segment, safe_join
from app.registry.scan import scan
from app.registry.validate import WorkflowEntry

router = APIRouter(prefix="/api")


class RegistryHolder:
    def __init__(self, workflows_dir: Path) -> None:
        self.workflows_dir = workflows_dir
        self.snapshot: list[WorkflowEntry] = scan(workflows_dir)

    def rescan(self) -> list[WorkflowEntry]:
        self.snapshot = scan(self.workflows_dir)
        return self.snapshot

    def get(self, workflow_id: str) -> WorkflowEntry | None:
        for entry in self.snapshot:
            if entry.folder_name == workflow_id:
                return entry
        return None


class ProblemOut(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"]


class WorkflowOut(BaseModel):
    id: str
    name: str | None
    description: str | None
    thumbnail_url: str | None
    valid: bool
    problems: list[ProblemOut]


class WorkflowListOut(BaseModel):
    workflows: list[WorkflowOut]


def _holder(request: Request) -> RegistryHolder:
    return cast(RegistryHolder, request.app.state.registry)


def _serialize(entry: WorkflowEntry) -> WorkflowOut:
    manifest = entry.manifest
    declared_thumb = None if manifest is None else manifest.workflow.thumbnail
    return WorkflowOut(
        id=entry.folder_name,
        name=None if manifest is None else manifest.workflow.name,
        description=None if manifest is None else manifest.workflow.description,
        thumbnail_url=(
            None if not declared_thumb else f"/api/workflows/{entry.folder_name}/thumbnail"
        ),
        valid=not any(problem.severity == "error" for problem in entry.problems),
        problems=[
            ProblemOut(code=problem.code.value, message=problem.message, severity=problem.severity)
            for problem in entry.problems
        ],
    )


def _list_payload(entries: list[WorkflowEntry]) -> WorkflowListOut:
    return WorkflowListOut(workflows=[_serialize(entry) for entry in entries])


@router.get("/workflows", response_model=WorkflowListOut)
def list_workflows(request: Request) -> WorkflowListOut:
    return _list_payload(_holder(request).snapshot)


@router.post("/workflows/rescan", response_model=WorkflowListOut)
def rescan_workflows(request: Request) -> WorkflowListOut:
    return _list_payload(_holder(request).rescan())


@router.get("/workflows/{workflow_id}/thumbnail")
def workflow_thumbnail(workflow_id: str, request: Request) -> FileResponse:
    if not is_safe_path_segment(workflow_id):
        raise HTTPException(status_code=404)
    entry = _holder(request).get(workflow_id)
    if entry is None or entry.manifest is None:
        raise HTTPException(status_code=404)
    declared = entry.manifest.workflow.thumbnail
    if not declared:
        raise HTTPException(status_code=404)
    path = safe_join(entry.path, declared)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404)
    media_type, _encoding = mimetypes.guess_type(path.name)
    return FileResponse(path, media_type=media_type or "application/octet-stream")
