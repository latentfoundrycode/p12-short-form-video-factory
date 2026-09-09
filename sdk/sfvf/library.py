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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    raise NotImplementedError


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
        raise NotImplementedError

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
        raise NotImplementedError

    def get(self, name_or_id: str) -> Asset | None:
        """Resolve a name or id to its asset, or None if it does not resolve to a stored sidecar."""
        raise NotImplementedError

    def resolve(self, name_or_id: str) -> str | None:
        """Return the id a name or id resolves to (alias first, then a stored id), else None."""
        raise NotImplementedError

    def blob_path(self, asset_id: str) -> Path:
        """The path of an asset's stored blob (`items/<id>`); may not exist for an unknown id."""
        raise NotImplementedError
