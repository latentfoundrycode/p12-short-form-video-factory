"""Library API — owner pool assets and workflow list for grant picker."""

import json
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sfvf.grants import GrantError, GrantStore, validate_grant
from sfvf.library import Asset, FacetSpec, LibraryStore

from app.api.workflows import _holder

router = APIRouter(prefix="/api")

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}
_VALID_KINDS = {"music", "sfx", "voice"}
_CHUNK_SIZE = 64 * 1024


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


def _asset_row(asset: Asset, grant: dict[str, Any]) -> LibraryAssetOut:
    return LibraryAssetOut(
        id=asset.id,
        kind=asset.kind,
        status=asset.status,
        facets=dict(asset.facets),
        description=asset.description,
        grant=grant,
    )


def _is_audio_upload(file: UploadFile) -> bool:
    content_type = file.content_type or ""
    if content_type.startswith("audio/"):
        return True
    filename = file.filename or ""
    return Path(filename).suffix.lower() in _AUDIO_EXTENSIONS


@router.get("/library/assets", response_model=LibraryAssetsOut)
def list_library_assets(request: Request) -> LibraryAssetsOut:
    owner_root = _owner_root(request)
    if not owner_root.is_dir():
        return LibraryAssetsOut(assets=[])
    store = LibraryStore(owner_root)
    grants = GrantStore(owner_root)
    assets = [
        _asset_row(asset, grants.get_grant(asset.id))
        for asset in store.find(status=None)
    ]
    return LibraryAssetsOut(assets=assets)


@router.post("/library/assets", response_model=LibraryAssetOut)
async def upload_library_asset(
    request: Request,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    grant: Annotated[str, Form()],
    mood: Annotated[str | None, Form()] = None,
    energy: Annotated[str | None, Form()] = None,
) -> LibraryAssetOut:
    if not _is_audio_upload(file):
        raise HTTPException(status_code=415, detail="unsupported media type")

    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=422, detail="invalid kind")

    try:
        validated_grant = validate_grant(json.loads(grant))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid grant JSON") from None
    except GrantError:
        raise HTTPException(status_code=422, detail="invalid grant") from None

    facets: dict[str, str] = {}
    if mood is not None:
        facets["mood"] = mood
    if energy is not None:
        facets["energy"] = energy

    owner_root = _owner_root(request)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_path = tmp.name
            total = 0
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="upload too large")
                tmp.write(chunk)

        store = LibraryStore(
            owner_root,
            facets=(FacetSpec("mood"), FacetSpec("energy")),
        )
        asset = store.put(name, Path(temp_path), kind=kind, facets=facets or None)
        GrantStore(owner_root).set_grant(asset.id, validated_grant)
        return _asset_row(asset, validated_grant)
    finally:
        if temp_path is not None:
            with suppress(OSError):
                Path(temp_path).unlink()


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
