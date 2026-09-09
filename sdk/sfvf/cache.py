"""Content-addressed step cache keyed on workflow version, family, and inputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_CHUNK = 1024 * 1024
_DICT_MARK = "__sfvf_dict__"
_FILE_SHA256_MARK = "__sfvf_file_sha256__"


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonicalize(value: object) -> object:
    if isinstance(value, Path):
        return {_FILE_SHA256_MARK: _file_digest(value)}
    if isinstance(value, dict):
        pairs = [[_canonicalize(key), _canonicalize(item)] for key, item in value.items()]
        pairs.sort(key=_canonical_json)
        return {_DICT_MARK: pairs}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def _reject_escaping_name(name: str) -> None:
    rel = Path(name)
    if rel.is_absolute() or rel.anchor or ".." in rel.parts:
        raise ValueError(f"cache file name is not a confined relative path: {name}")


def step_key(workflow_version: str, family: str, inputs: dict[str, Any]) -> str:
    payload: list[object] = [workflow_version, family, _canonicalize(inputs)]
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _copy_atomic(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            with src.open("rb") as reader:
                shutil.copyfileobj(reader, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, dest)  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


CHEAP = "cheap"
PAID = "paid"


class StepCache:
    """Filesystem store for a step's JSON result and content-addressed files.

    A cache is split into two partitions with different deletion policies (§5.9): ``paid`` results
    of paid generation (never auto-evicted) and ``cheap`` renders/research (LRU-evicted past a size
    limit — see `evict_cheap`). Each partition is a self-contained ``<root>/<partition>/entries`` +
    ``<root>/<partition>/blobs`` subtree so eviction of one can never touch the other's blobs.
    """

    def __init__(
        self,
        root: Path,
        *,
        partition: str = CHEAP,
        now: Callable[[], float] = time.time,
    ) -> None:
        # SKELETON (C-6): the builder routes entries/blobs under `partition` and records/refreshes
        # a `last_used` recency stamp using `now`. Until then the layout is unchanged so the
        # existing single-partition behaviour holds.
        self._root = root
        self._partition = partition
        self._now = now
        self._entries = root / "entries"
        self._blobs = root / "blobs"

    def _entry_path(self, key: str) -> Path:
        return self._entries / key

    def _blob_path(self, digest: str) -> Path:
        return self._blobs / digest

    def get(self, key: str, *, restore_into: Path | None = None) -> Any | None:
        path = self._entry_path(key)
        if not path.is_file():
            return None
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError(f"cache entry is not a JSON object: {path}")
        if restore_into is not None:
            stored = raw.get("files", {})
            if isinstance(stored, dict):
                restore_root = restore_into.resolve()
                confined: list[tuple[Path, str]] = []
                for relative, digest in stored.items():
                    if not isinstance(relative, str) or not isinstance(digest, str):
                        continue
                    _reject_escaping_name(relative)
                    dest = restore_into / relative
                    if not dest.resolve().is_relative_to(restore_root):
                        raise ValueError(f"cache restore path escapes restore_into: {relative}")
                    confined.append((dest, digest))
                for dest, digest in confined:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self._blob_path(digest), dest)
        return raw["value"]

    def put(
        self,
        key: str,
        value: Any,
        *,
        files: Mapping[str, Path] | None = None,
    ) -> None:
        mapping: dict[str, str] = {}
        if files:
            for relative in files:
                _reject_escaping_name(relative)
            for relative, src in files.items():
                digest = _file_digest(src)
                dest = self._blob_path(digest)
                if not dest.is_file():
                    _copy_atomic(src, dest)
                mapping[relative] = digest
        _write_json_atomic(self._entry_path(key), {"value": value, "files": mapping})


def evict_cheap(root: Path, *, max_bytes: int) -> int:
    """Least-recently-used eviction of the ``cheap`` partition under `root` (§5.9).

    Computes the cheap partition's total size (entry files + blob files). If it is within
    `max_bytes`, nothing is removed and 0 is returned. Otherwise the least-recently-used entries
    (oldest `last_used` first) are removed until the total fits, and afterwards any blob no longer
    referenced by a surviving cheap entry is deleted — so a blob shared by a surviving entry is
    kept. The ``paid`` partition is never touched. Returns the number of entries removed.

    SKELETON — the body is filled by the builder (C-6).
    """
    raise NotImplementedError
