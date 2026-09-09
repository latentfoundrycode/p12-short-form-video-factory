"""The library: durable, content-addressed assets that outlive a run (SDK §7, Architecture §5.10).

Unlike the cache, the library is NAMED, DESCRIBED, never auto-evicted, and unaffected by a
workflow's version — the cache remembers work, the library holds things (§2.1b). An asset is a blob
named by the sha256 of its contents, with an authoritative descriptor sidecar beside it; a name in
`aliases.json` is a mutable handle pointing at an id, so "the current Bertie" resolves to whichever
sheet is current while a recorded id still resolves forever.

This module is the content-addressed STORE: `put`/`get`/`resolve`, facet declaration +
normalisation, atomic blob→sidecar writes, and the derived `catalog.json` index (`find()`,
novelty, crash-recovery rescan). The `ctx.library` runtime API, describe/value/annotate,
supersession and the dry-run overlay are D-3.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from .cache import _copy_atomic, _file_digest, _write_json_atomic

_SHA256_HEX = frozenset("0123456789abcdef")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_sha256_id(value: str) -> bool:
    return len(value) == 64 and all(char in _SHA256_HEX for char in value)


class _CatalogEntry(TypedDict):
    status: str
    kind: str
    tags: list[str]
    facets: dict[str, str]
    created_utc: str
    novel_facets: list[str]


class _CatalogDoc(TypedDict):
    assets: dict[str, _CatalogEntry]
    quarantined: list[str]
    dropped: list[str]


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


@dataclass(frozen=True)
class RebuildReport:
    """Outcome of a catalogue rescan (§5.10 crash-recovery table). Nothing is ever deleted.

    `indexed` counts assets in the rebuilt index. `quarantined` are ids of a blob with no sidecar
    (crashed before describing — kept and flagged, never indexed). `dropped` are ids of a sidecar
    with no blob (impossible under blob→sidecar ordering; removed from the index and flagged).
    """

    indexed: int
    quarantined: tuple[str, ...]
    dropped: tuple[str, ...]


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
        self._catalog = root / "catalog.json"
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
            # Self-heal: if a crash between the sidecar and catalogue writes left this described
            # asset unindexed, a rescan recovers it (and any siblings) rather than leaving it
            # invisible to find() until the next explicit rebuild.
            catalog = self._try_read_catalog()
            if catalog is None or asset_id not in catalog["assets"]:
                self.rebuild_catalog()
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
            self._index_new_asset(asset)
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

    def find(
        self,
        *,
        tags: Sequence[str] = (),
        facets: Mapping[str, str] | None = None,
        status: str | None = "active",
    ) -> list[Asset]:
        """Return assets matching every requested tag and facet, filtered by status (§7.5).

        Reads the derived `catalog.json` (rebuilt from `items/` if absent). Matching is exact and
        deterministic: an asset matches when it carries every requested tag and, for each requested
        facet, holds exactly that (normalised) value — an absent facet never matches a query for it
        (§7.4). `status` None means any status; otherwise only assets of that status. Results are
        ordered deterministically (by `created_utc`, then id). Free and pure — the cheap first tier
        of selection, before an agent reads descriptions.
        """
        catalog = self._load_catalog_or_rebuild()
        wanted_tags = tuple(tags)
        wanted_facets = {key: normalise_facet_value(value) for key, value in (facets or {}).items()}
        matched: list[tuple[str, str]] = []
        for asset_id, entry in catalog["assets"].items():
            if status is not None and entry["status"] != status:
                continue
            entry_tags = entry["tags"]
            if any(tag not in entry_tags for tag in wanted_tags):
                continue
            entry_facets = entry["facets"]
            if any(entry_facets.get(key) != value for key, value in wanted_facets.items()):
                continue
            matched.append((entry["created_utc"], asset_id))
        matched.sort()
        found: list[Asset] = []
        for _, asset_id in matched:
            asset = self.get(asset_id)
            if asset is not None:
                found.append(asset)
        return found

    def rebuild_catalog(self) -> RebuildReport:
        """Rescan `items/` and rewrite `catalog.json`, returning what was found (§5.10).

        Idempotent. A blob with no sidecar is quarantined and flagged (never deleted — it cost);
        a sidecar with no blob is dropped from the index and flagged; a described asset not yet
        indexed is indexed. Novelty (`novel_facets`) is recomputed: for each open facet key, the
        earliest asset (by created_utc, then id) to carry a given value is marked as introducing it.
        """
        blobs, sidecars = self._scan_item_ids()
        indexed_ids = blobs & sidecars
        dropped = tuple(sorted(sidecars - blobs))
        loaded: list[Asset] = []
        corrupt: set[str] = set()
        for asset_id in sorted(indexed_ids):
            try:
                asset = self.get(asset_id)
            except (OSError, ValueError, TypeError):
                asset = None
            if asset is None:
                # Sidecar unreadable/corrupt: flag it, keep the (paid) blob, do not index it. The
                # rescan tolerates bad files by inspection rather than aborting (§5.10).
                corrupt.add(asset_id)
                continue
            loaded.append(asset)
        quarantined = tuple(sorted((blobs - sidecars) | corrupt))
        loaded.sort(key=lambda asset: (asset.created_utc, asset.id))
        seen: dict[str, set[str]] = {}
        assets: dict[str, _CatalogEntry] = {}
        for asset in loaded:
            novel = self._novel_keys(asset.facets, seen)
            assets[asset.id] = _entry_from_asset(asset, novel)
        catalog: _CatalogDoc = {
            "assets": assets,
            "quarantined": list(quarantined),
            "dropped": list(dropped),
        }
        _write_json_atomic(self._catalog, catalog)
        return RebuildReport(indexed=len(assets), quarantined=quarantined, dropped=dropped)

    def novel_facets(self, asset_id: str) -> tuple[str, ...]:
        """The open-facet keys whose value this asset was the first to introduce (§7.4).

        Read from the catalogue; empty when the asset introduced no new value or is unknown. The
        `library` event that surfaces novelty in the record is emitted by the ctx wrapper (D-3).
        """
        catalog = self._load_catalog_or_rebuild()
        entry = catalog["assets"].get(asset_id)
        if entry is None:
            return ()
        return tuple(entry["novel_facets"])

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

    def _index_new_asset(self, asset: Asset) -> None:
        catalog = self._try_read_catalog()
        if catalog is None:
            # Sidecar is already on disk; a full rescan recovers any siblings the missing
            # index would have omitted, and records this asset's novelty.
            self.rebuild_catalog()
            return
        catalog["assets"].pop(asset.id, None)
        seen = self._seen_open_values(catalog["assets"])
        novel = self._novel_keys(asset.facets, seen)
        catalog["assets"][asset.id] = _entry_from_asset(asset, novel)
        _write_json_atomic(self._catalog, catalog)

    def _load_catalog_or_rebuild(self) -> _CatalogDoc:
        catalog = self._try_read_catalog()
        if catalog is not None:
            return catalog
        self.rebuild_catalog()
        catalog = self._try_read_catalog()
        if catalog is not None:
            return catalog
        return {"assets": {}, "quarantined": [], "dropped": []}

    def _try_read_catalog(self) -> _CatalogDoc | None:
        path = self._catalog
        if not path.is_file():
            return None
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return _coerce_catalog(raw)

    def _scan_item_ids(self) -> tuple[set[str], set[str]]:
        blobs: set[str] = set()
        sidecars: set[str] = set()
        if not self._items.is_dir():
            return blobs, sidecars
        suffix = ".json"
        for path in self._items.iterdir():
            if not path.is_file():
                continue
            name = path.name
            if name.endswith(suffix):
                asset_id = name[: -len(suffix)]
                if _is_sha256_id(asset_id):
                    sidecars.add(asset_id)
            elif _is_sha256_id(name):
                blobs.add(name)
        return blobs, sidecars

    def _seen_open_values(self, assets: Mapping[str, _CatalogEntry]) -> dict[str, set[str]]:
        seen: dict[str, set[str]] = {}
        for entry in assets.values():
            for key, value in entry["facets"].items():
                if self._is_open_key(key):
                    seen.setdefault(key, set()).add(value)
        return seen

    def _novel_keys(self, facets: Mapping[str, str], seen: dict[str, set[str]]) -> list[str]:
        novel: list[str] = []
        for key, value in facets.items():
            if not self._is_open_key(key):
                continue
            known = seen.setdefault(key, set())
            if value not in known:
                novel.append(key)
                known.add(value)
        return novel

    def _is_open_key(self, key: str) -> bool:
        spec = self._facets.get(key)
        return spec is not None and spec.values is None


def _entry_from_asset(asset: Asset, novel: Sequence[str]) -> _CatalogEntry:
    return {
        "status": asset.status,
        "kind": asset.kind,
        "tags": list(asset.tags),
        "facets": dict(asset.facets),
        "created_utc": asset.created_utc,
        "novel_facets": list(novel),
    }


def _coerce_catalog(raw: object) -> _CatalogDoc | None:
    # A structurally-incomplete doc (missing "assets") is a torn/foreign catalogue, not a legitimate
    # empty one — return None so the caller rebuilds from the authoritative sidecars rather than
    # trusting an empty index (§5.10: the catalogue self-heals when doubted). A real empty library
    # is written as {"assets": {}, ...} by rebuild_catalog, so the key is always present when valid.
    if not isinstance(raw, dict) or "assets" not in raw:
        return None
    assets_raw = raw["assets"]
    if not isinstance(assets_raw, dict):
        return None
    assets: dict[str, _CatalogEntry] = {}
    for asset_id, entry_raw in assets_raw.items():
        if isinstance(asset_id, str) and isinstance(entry_raw, dict):
            assets[asset_id] = _coerce_entry(entry_raw)
    quarantined = _string_list(raw.get("quarantined", []))
    dropped = _string_list(raw.get("dropped", []))
    return {"assets": assets, "quarantined": quarantined, "dropped": dropped}


def _coerce_entry(raw: Mapping[Any, Any]) -> _CatalogEntry:
    tags_raw = raw.get("tags", [])
    tags = [str(item) for item in tags_raw] if isinstance(tags_raw, list) else []
    facets_raw = raw.get("facets") or {}
    facets = (
        {str(key): str(value) for key, value in facets_raw.items()}
        if isinstance(facets_raw, dict)
        else {}
    )
    novel_raw = raw.get("novel_facets", [])
    novel = [str(item) for item in novel_raw] if isinstance(novel_raw, list) else []
    return {
        "status": str(raw.get("status", "active")),
        "kind": str(raw.get("kind", "file")),
        "tags": tags,
        "facets": facets,
        "created_utc": str(raw.get("created_utc", "")),
        "novel_facets": novel,
    }


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str)]
