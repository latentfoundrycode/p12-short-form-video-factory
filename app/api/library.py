"""Library API — owner pool assets and workflow list for grant picker."""

import json
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sfvf.grants import GrantError, GrantStore, validate_grant
from sfvf.library import Asset, FacetSpec, LibraryError, LibraryStore

from app.api.workflows import _holder

router = APIRouter(prefix="/api")

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}
_VALID_KINDS = {"music", "sfx", "voice"}
_CHUNK_SIZE = 64 * 1024
_SHA256_HEX = frozenset("0123456789abcdef")


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


class LibraryAssetAnnotateIn(BaseModel):
    facets: dict[str, str] | None = None
    caveats: str | None = None


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


def _is_valid_asset_id(asset_id: str) -> bool:
    return len(asset_id) == 64 and all(char in _SHA256_HEX for char in asset_id)


def _facet_store(owner_root: Path) -> LibraryStore:
    return LibraryStore(owner_root, facets=(FacetSpec("mood"), FacetSpec("energy")))


def _require_owner_asset(request: Request, asset_id: str) -> Asset:
    if not _is_valid_asset_id(asset_id):
        raise HTTPException(status_code=404)
    asset = LibraryStore(_owner_root(request)).get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    return asset


def _updated_row(request: Request, asset: Asset) -> LibraryAssetOut:
    grant = GrantStore(_owner_root(request)).get_grant(asset.id)
    return _asset_row(asset, grant)


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


@router.put("/library/assets/{asset_id}", response_model=LibraryAssetOut)
def update_library_asset(
    request: Request,
    asset_id: str,
    body: LibraryAssetAnnotateIn,
) -> LibraryAssetOut:
    _require_owner_asset(request, asset_id)
    annotate_kwargs: dict[str, Any] = {}
    if "facets" in body.model_fields_set:
        annotate_kwargs["facets"] = body.facets
    if "caveats" in body.model_fields_set:
        annotate_kwargs["caveats"] = body.caveats
    try:
        asset = _facet_store(_owner_root(request)).annotate(asset_id, **annotate_kwargs)
    except LibraryError:
        raise HTTPException(status_code=422, detail="invalid annotation") from None
    return _updated_row(request, asset)


@router.post("/library/assets/{asset_id}/grant", response_model=LibraryAssetOut)
def set_library_asset_grant(
    request: Request,
    asset_id: str,
    body: dict[str, Any],
) -> LibraryAssetOut:
    asset = _require_owner_asset(request, asset_id)
    try:
        validated_grant = validate_grant(body)
    except GrantError:
        raise HTTPException(status_code=422, detail="invalid grant") from None
    GrantStore(_owner_root(request)).set_grant(asset_id, validated_grant)
    return _asset_row(asset, validated_grant)


@router.post("/library/assets/{asset_id}/deactivate", response_model=LibraryAssetOut)
def deactivate_library_asset(request: Request, asset_id: str) -> LibraryAssetOut:
    _require_owner_asset(request, asset_id)
    asset = LibraryStore(_owner_root(request)).deactivate(asset_id)
    return _updated_row(request, asset)


@router.post("/library/assets/{asset_id}/reactivate", response_model=LibraryAssetOut)
def reactivate_library_asset(request: Request, asset_id: str) -> LibraryAssetOut:
    _require_owner_asset(request, asset_id)
    asset = LibraryStore(_owner_root(request)).reactivate(asset_id)
    return _updated_row(request, asset)


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
