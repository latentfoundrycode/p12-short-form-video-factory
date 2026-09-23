import mimetypes
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sfvf.context import BudgetConfig
from sfvf.providers import capabilities_offered

from app.paths import is_safe_path_segment, safe_join
from app.registry.scan import scan
from app.registry.validate import WorkflowEntry

router = APIRouter(prefix="/api")


def _serpapi_has_ceiling(budget: BudgetConfig | None) -> bool:
    return budget is not None and ("serpapi" in budget.per_run or "serpapi" in budget.per_day)


class RegistryHolder:
    def __init__(
        self,
        workflows_dir: Path,
        *,
        configured: set[str] | None = None,
        disabled_web_tiers: list[str] | None = None,
        budget: BudgetConfig | None = None,
    ) -> None:
        self.workflows_dir = workflows_dir
        offered = None if configured is None else capabilities_offered(set(configured))
        if offered is not None:
            if disabled_web_tiers:
                offered = offered - {f"web.images.{tier}" for tier in disabled_web_tiers}
            # DESIGN §6: the paid web tier needs a configured ceiling for its meter;
            # without one every web search is refused at runtime, so the capability
            # must not be offered.
            if "web.images.web" in offered and not _serpapi_has_ceiling(budget):
                offered = offered - {"web.images.web"}
        self._offered: frozenset[str] | None = offered
        self.snapshot: list[WorkflowEntry] = scan(workflows_dir, offered=self._offered)

    def rescan(self) -> list[WorkflowEntry]:
        self.snapshot = scan(self.workflows_dir, offered=self._offered)
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


class QualityFactorOut(BaseModel):
    key: str
    question: str


class ParamOut(BaseModel):
    key: str
    type: str
    label: str
    required: bool
    default: Any
    help: str | None
    affects_cost: bool
    min: float | None
    max: float | None
    step: float | None
    options: list[Any] | None
    options_from: str | None
    placeholder: str | None
    unit: str | None


class WorkflowOut(BaseModel):
    id: str
    name: str | None
    description: str | None
    thumbnail_url: str | None
    valid: bool
    problems: list[ProblemOut]
    quality_factors: list[QualityFactorOut]
    params: list[ParamOut]


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
        quality_factors=(
            []
            if manifest is None
            else [
                QualityFactorOut(key=f.key, question=f.question) for f in manifest.quality_factors
            ]
        ),
        params=(
            []
            if manifest is None
            else [
                ParamOut(
                    key=param.key,
                    type=param.type,
                    label=param.label,
                    required=param.required,
                    default=param.default,
                    help=param.help,
                    affects_cost=param.affects_cost,
                    min=param.min,
                    max=param.max,
                    step=param.step,
                    options=param.options,
                    options_from=param.options_from,
                    placeholder=param.placeholder,
                    unit=param.unit,
                )
                for param in manifest.params
            ]
        ),
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
