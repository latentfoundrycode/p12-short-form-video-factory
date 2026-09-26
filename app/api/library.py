"""Library API — owner pool assets and workflow list for grant picker."""

import json
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sfvf.grants import GrantError, GrantStore, validate_grant
from sfvf.library import Asset, LibraryError, LibraryStore, normalise_facet_value
from sfvf.media.speech import bundled_voice_presets

from app.api.workflows import _holder

router = APIRouter(prefix="/api")

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}
_VALID_KINDS = {"music", "sfx", "voice"}
_CHUNK_SIZE = 64 * 1024
_SHA256_HEX = frozenset("0123456789abcdef")
_MOOD_PREFIX = "mood:"
_ENERGY_PREFIX = "energy:"


class LibraryAssetOut(BaseModel):
    id: str
    name: str | None
    kind: str
    status: str
    mood: list[str]
    energy: list[str]
    description: str
    grant: dict[str, Any]


class LibraryAssetsOut(BaseModel):
    assets: list[LibraryAssetOut]


class LibraryWorkflowOut(BaseModel):
    id: str
    label: str


class LibraryWorkflowsOut(BaseModel):
    workflows: list[LibraryWorkflowOut]


class LibraryVoiceOut(BaseModel):
    id: str
    label: str
    source: str


class LibraryVoicesOut(BaseModel):
    voices: list[LibraryVoiceOut]


class LibraryAssetUpdateIn(BaseModel):
    name: str | None = None
    kind: str | None = None
    mood: list[str] | None = None
    energy: list[str] | None = None
    caveats: str | None = None


def _library_dir(request: Request) -> Path:
    return cast(Path, request.app.state.library_dir)


def _owner_root(request: Request) -> Path:
    return _library_dir(request) / "_owner"


def _split_mood_energy(tags: tuple[str, ...]) -> tuple[list[str], list[str]]:
    mood: list[str] = []
    energy: list[str] = []
    for tag in tags:
        if tag.startswith(_MOOD_PREFIX):
            mood.append(tag[len(_MOOD_PREFIX) :])
        elif tag.startswith(_ENERGY_PREFIX):
            energy.append(tag[len(_ENERGY_PREFIX) :])
    return mood, energy


def _mood_energy_tags(mood: list[str], energy: list[str]) -> list[str]:
    tags: list[str] = []
    for value in mood:
        tags.append(f"{_MOOD_PREFIX}{normalise_facet_value(value)}")
    for value in energy:
        tags.append(f"{_ENERGY_PREFIX}{normalise_facet_value(value)}")
    return tags


def _asset_row(asset: Asset, grant: dict[str, Any], store: LibraryStore) -> LibraryAssetOut:
    mood, energy = _split_mood_energy(asset.tags)
    return LibraryAssetOut(
        id=asset.id,
        name=store.name_for(asset.id),
        kind=asset.kind,
        status=asset.status,
        mood=mood,
        energy=energy,
        description=asset.caveats,
        grant=grant,
    )


def _is_valid_asset_id(asset_id: str) -> bool:
    return len(asset_id) == 64 and all(char in _SHA256_HEX for char in asset_id)


def _owner_store(owner_root: Path) -> LibraryStore:
    return LibraryStore(owner_root)


def _require_owner_asset(request: Request, asset_id: str) -> Asset:
    if not _is_valid_asset_id(asset_id):
        raise HTTPException(status_code=404)
    asset = _owner_store(_owner_root(request)).get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    return asset


def _updated_row(request: Request, asset: Asset) -> LibraryAssetOut:
    owner_root = _owner_root(request)
    grant = GrantStore(owner_root).get_grant(asset.id)
    return _asset_row(asset, grant, _owner_store(owner_root))


def _parse_tag_array(raw: str | None) -> list[str]:
    if raw is None:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="invalid mood/energy JSON") from None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=422, detail="invalid mood/energy JSON")
    return parsed


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
    store = _owner_store(owner_root)
    grants = GrantStore(owner_root)
    assets = [
        _asset_row(asset, grants.get_grant(asset.id), store) for asset in store.find(status=None)
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

    mood_tags = _parse_tag_array(mood)
    energy_tags = _parse_tag_array(energy)
    tags = _mood_energy_tags(mood_tags, energy_tags)

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

        store = _owner_store(owner_root)
        asset = store.put(name, Path(temp_path), kind=kind, tags=tags)
        GrantStore(owner_root).set_grant(asset.id, validated_grant)
        return _asset_row(asset, validated_grant, store)
    finally:
        if temp_path is not None:
            with suppress(OSError):
                Path(temp_path).unlink()


@router.put("/library/assets/{asset_id}", response_model=LibraryAssetOut)
def update_library_asset(
    request: Request,
    asset_id: str,
    body: LibraryAssetUpdateIn,
) -> LibraryAssetOut:
    asset = _require_owner_asset(request, asset_id)
    owner_root = _owner_root(request)
    store = _owner_store(owner_root)

    if "name" in body.model_fields_set:
        if body.name is None or not body.name.strip():
            raise HTTPException(status_code=422, detail="invalid name")
        try:
            store.rename(asset_id, body.name.strip())
        except LibraryError:
            raise HTTPException(status_code=404) from None

    annotate_kwargs: dict[str, Any] = {}
    if "kind" in body.model_fields_set:
        if body.kind not in _VALID_KINDS:
            raise HTTPException(status_code=422, detail="invalid kind")
        annotate_kwargs["kind"] = body.kind
    if "mood" in body.model_fields_set or "energy" in body.model_fields_set:
        current_mood, current_energy = _split_mood_energy(asset.tags)
        mood = body.mood if "mood" in body.model_fields_set else current_mood
        energy = body.energy if "energy" in body.model_fields_set else current_energy
        if mood is None or energy is None:
            raise HTTPException(status_code=422, detail="invalid mood/energy")
        other_tags = [
            tag
            for tag in asset.tags
            if not tag.startswith(_MOOD_PREFIX) and not tag.startswith(_ENERGY_PREFIX)
        ]
        annotate_kwargs["tags"] = other_tags + _mood_energy_tags(mood, energy)
    if "caveats" in body.model_fields_set:
        annotate_kwargs["caveats"] = body.caveats

    if annotate_kwargs:
        try:
            asset = store.annotate(asset_id, **annotate_kwargs)
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
    owner_root = _owner_root(request)
    GrantStore(owner_root).set_grant(asset_id, validated_grant)
    return _asset_row(asset, validated_grant, _owner_store(owner_root))


@router.post("/library/assets/{asset_id}/deactivate", response_model=LibraryAssetOut)
def deactivate_library_asset(request: Request, asset_id: str) -> LibraryAssetOut:
    _require_owner_asset(request, asset_id)
    asset = _owner_store(_owner_root(request)).deactivate(asset_id)
    return _updated_row(request, asset)


@router.post("/library/assets/{asset_id}/reactivate", response_model=LibraryAssetOut)
def reactivate_library_asset(request: Request, asset_id: str) -> LibraryAssetOut:
    _require_owner_asset(request, asset_id)
    asset = _owner_store(_owner_root(request)).reactivate(asset_id)
    return _updated_row(request, asset)


@router.get("/library/voices", response_model=LibraryVoicesOut)
def list_library_voices(request: Request) -> LibraryVoicesOut:
    voices: list[LibraryVoiceOut] = [
        LibraryVoiceOut(id=preset["id"], label=preset["label"], source="preset")
        for preset in bundled_voice_presets()
    ]
    owner_root = _owner_root(request)
    if owner_root.is_dir():
        store = _owner_store(owner_root)
        for asset in store.find(status="active"):
            if asset.kind != "voice":
                continue
            label = store.name_for(asset.id) or asset.id
            voices.append(LibraryVoiceOut(id=asset.id, label=label, source="asset"))
    return LibraryVoicesOut(voices=voices)


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
