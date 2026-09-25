"""Library API — owner pool assets and workflow list for grant picker."""

from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sfvf.grants import GrantStore
from sfvf.library import LibraryStore

from app.api.workflows import _holder

router = APIRouter(prefix="/api")


class LibraryAssetOut(BaseModel):
    id: str
    kind: str
    status: str
    facets: dict[str, str]
    description: str
    grant: dict[str, Any]


class LibraryAssetsOut(BaseModel):
    assets: list[LibraryAssetOut]


class LibraryWorkflowOut(BaseModel):
    id: str
    label: str


class LibraryWorkflowsOut(BaseModel):
    workflows: list[LibraryWorkflowOut]


def _library_dir(request: Request) -> Path:
    return cast(Path, request.app.state.library_dir)


def _owner_root(request: Request) -> Path:
    return _library_dir(request) / "_owner"


@router.get("/library/assets", response_model=LibraryAssetsOut)
def list_library_assets(request: Request) -> LibraryAssetsOut:
    owner_root = _owner_root(request)
    if not owner_root.is_dir():
        return LibraryAssetsOut(assets=[])
    store = LibraryStore(owner_root)
    grants = GrantStore(owner_root)
    assets = [
        LibraryAssetOut(
            id=asset.id,
            kind=asset.kind,
            status=asset.status,
            facets=dict(asset.facets),
            description=asset.description,
            grant=grants.get_grant(asset.id),
        )
        for asset in store.find(status=None)
    ]
    return LibraryAssetsOut(assets=assets)


@router.get("/library/workflows", response_model=LibraryWorkflowsOut)
def list_library_workflows(request: Request) -> LibraryWorkflowsOut:
    rows: list[LibraryWorkflowOut] = []
    for entry in _holder(request).snapshot:
        if entry.manifest is None:
            continue
        rows.append(
            LibraryWorkflowOut(
                id=entry.manifest.workflow.id,
                label=entry.manifest.workflow.name,
            )
        )
    rows.sort(key=lambda row: row.id)
    return LibraryWorkflowsOut(workflows=rows)
