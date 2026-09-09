"""The library: durable, content-addressed assets that outlive a run (SDK §7, Architecture §5.10).

Unlike the cache, the library is NAMED, DESCRIBED, never auto-evicted, and unaffected by a
workflow's version — the cache remembers work, the library holds things (§2.1b). An asset is a blob
named by the sha256 of its contents, with an authoritative descriptor sidecar beside it; a name in
`aliases.json` is a mutable handle pointing at an id, so "the current Bertie" resolves to whichever
sheet is current while a recorded id still resolves forever.

This module is the content-addressed STORE: `put`/`get`/`resolve`, facet declaration +
normalisation, and atomic blob→sidecar writes. The catalogue index, `find()`, novelty, and
crash-recovery rescan are a later increment (D-2); the `ctx.library` runtime API,
describe/value/annotate, supersession and the dry-run overlay are D-3.

SKELETON — the public names/signatures are frozen by tests/sdk/test_library_store.py; the builder
fills the bodies.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cache import _copy_atomic, _file_digest, _write_json_atomic

_SHA256_HEX = frozenset("0123456789abcdef")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_sha256_id(value: str) -> bool:
    return len(value) == 64 and all(char in _SHA256_HEX for char in value)


class LibraryError(ValueError):
    """A write violates the declared facet vocabulary (undeclared key or closed-set violation)."""


@dataclass(frozen=True)
class FacetSpec:
    """A declared facet: its key and either open free text or a closed set of allowed values.

    `values` is None for an open key (values are normalised free text) or a tuple of allowed values
    for a closed key (a value outside the set is rejected at write — §7.4).
    """

    key: str
    values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Asset:
    """An asset's descriptor (the authoritative sidecar content). `id` is the blob's sha256."""

    id: str
    kind: str
    status: str
    created_utc: str
    supersedes: str | None
    tags: tuple[str, ...]
    facets: dict[str, str]
    description: str
    caveats: str
    provenance: dict[str, Any]


def normalise_facet_value(value: str) -> str:
    """Normalise an open facet value so trivial variants converge (§7.4).

    Lowercase, strip surrounding whitespace, and collapse any run of internal whitespace to a single
    hyphen — so "Rain Coat" and "  rain coat " both become "rain-coat".
    """
    return "-".join(value.lower().split())


class LibraryStore:
    """Content-addressed asset store rooted at one namespace directory (`library/<namespace>`).

    `facets` declares the allowed facet vocabulary; `put` rejects an undeclared key and a closed-set
    violation, and normalises open values. `now` is injectable for deterministic `created_utc`.
    """

    def __init__(
        self,
        root: Path,
        *,
        facets: Sequence[FacetSpec] = (),
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._root = root
        self._now = now
        self._items = root / "items"
        self._aliases = root / "aliases.json"
        self._facets: dict[str, FacetSpec] = {}
        for spec in facets:
            if spec.values is None:
                self._facets[spec.key] = spec
            else:
                self._facets[spec.key] = FacetSpec(
                    spec.key,
                    tuple(normalise_facet_value(value) for value in spec.values),
                )

    def put(
        self,
        name: str | None,
        source: Path,
        *,
        kind: str = "file",
        tags: Sequence[str] = (),
        facets: Mapping[str, str] | None = None,
        description: str = "",
        caveats: str = "",
        supersedes: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> Asset:
        """Store `source` as an asset and return its descriptor.

        The id is the sha256 of the file's contents (identical content is one blob, stored once).
        Writes the blob first, then the authoritative sidecar (so a crash leaves at worst a
        blob-without-sidecar, never the reverse), both atomically (temp name then rename). When
        `name` is given, sets the mutable alias `name -> id` in `aliases.json`. Facet keys must be
        declared; a closed-set violation or undeclared key raises `LibraryError`; open values are
        normalised via `normalise_facet_value`.
        """
        asset_id = _file_digest(source)
        stored_facets = self._normalise_facets(facets)  # always validate, even on re-put
        blob = self._items / asset_id
        sidecar = self._items / f"{asset_id}.json"
        # Content already stored: an asset is never replaced in place (§7.7), so keep its
        # established descriptor (its accumulated caveats/provenance) and only (re)point the name
        # below. To change metadata a caller uses annotate(); to change content, a new asset wins.
        existing = self.get(asset_id) if sidecar.is_file() else None
        if existing is not None:
            asset = existing
        else:
            stored_tags = tuple(tags)
            stored_provenance = dict(provenance) if provenance is not None else {}
            created_utc = self._now().astimezone(UTC).isoformat().replace("+00:00", "Z")
            if not blob.is_file():
                _copy_atomic(source, blob)
            _write_json_atomic(
                sidecar,
                {
                    "id": asset_id,
                    "kind": kind,
                    "created_utc": created_utc,
                    "status": "active",
                    "supersedes": supersedes,
                    "tags": list(stored_tags),
                    "facets": stored_facets,
                    "description": description,
                    "caveats": caveats,
                    "provenance": stored_provenance,
                },
            )
            asset = Asset(
                id=asset_id,
                kind=kind,
                status="active",
                created_utc=created_utc,
                supersedes=supersedes,
                tags=stored_tags,
                facets=stored_facets,
                description=description,
                caveats=caveats,
                provenance=stored_provenance,
            )
        if name is not None:
            aliases = self._load_aliases()
            aliases[name] = asset_id
            _write_json_atomic(self._aliases, aliases)
        return asset

    def get(self, name_or_id: str) -> Asset | None:
        """Resolve a name or id to its asset, or None if it does not resolve to a stored sidecar."""
        asset_id = self.resolve(name_or_id)
        if asset_id is None:
            return None
        path = self._items / f"{asset_id}.json"
        if not path.is_file():
            return None
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError(f"library sidecar is not a JSON object: {path}")
        tags_raw = raw.get("tags", [])
        tags = tuple(str(item) for item in tags_raw) if isinstance(tags_raw, list) else ()
        facets_raw = raw.get("facets") or {}
        stored_facets = (
            {str(key): str(value) for key, value in facets_raw.items()}
            if isinstance(facets_raw, dict)
            else {}
        )
        provenance_raw = raw.get("provenance") or {}
        provenance: dict[str, Any] = (
            {str(key): value for key, value in provenance_raw.items()}
            if isinstance(provenance_raw, dict)
            else {}
        )
        supersedes_raw = raw.get("supersedes")
        return Asset(
            id=str(raw.get("id", asset_id)),
            kind=str(raw.get("kind", "file")),
            status=str(raw.get("status", "active")),
            created_utc=str(raw.get("created_utc", "")),
            supersedes=supersedes_raw if isinstance(supersedes_raw, str) else None,
            tags=tags,
            facets=stored_facets,
            description=str(raw.get("description", "")),
            caveats=str(raw.get("caveats", "")),
            provenance=provenance,
        )

    def resolve(self, name_or_id: str) -> str | None:
        """Return the id a name or id resolves to (alias first, then a stored id), else None."""
        aliases = self._load_aliases()
        if name_or_id in aliases:
            return aliases[name_or_id]
        if _is_sha256_id(name_or_id) and (self._items / f"{name_or_id}.json").is_file():
            return name_or_id
        return None

    def blob_path(self, asset_id: str) -> Path:
        """The path of an asset's stored blob (`items/<id>`); may not exist for an unknown id."""
        return self._items / asset_id

    def _normalise_facets(self, facets: Mapping[str, str] | None) -> dict[str, str]:
        stored: dict[str, str] = {}
        for key, value in (facets or {}).items():
            spec = self._facets.get(key)
            if spec is None:
                raise LibraryError(f"undeclared facet key: {key}")
            normalised = normalise_facet_value(value)
            allowed = spec.values
            if allowed is not None and normalised not in allowed:
                raise LibraryError(f"facet {key!r} value {normalised!r} is not in the closed set")
            stored[key] = normalised
        return stored

    def _load_aliases(self) -> dict[str, str]:
        path = self._aliases
        if not path.is_file():
            return {}
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError(f"library aliases is not a JSON object: {path}")
        aliases: dict[str, str] = {}
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, str):
                aliases[key] = value
        return aliases
