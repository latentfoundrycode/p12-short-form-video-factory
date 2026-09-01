"""Content-addressed step cache keyed on workflow version, family, and inputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_CHUNK = 1024 * 1024


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _canonicalize(value: object) -> object:
    if isinstance(value, Path):
        return _file_digest(value)
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def step_key(workflow_version: str, family: str, inputs: dict[str, Any]) -> str:
    payload: list[object] = [workflow_version, family, _canonicalize(inputs)]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


class StepCache:
    """Filesystem store for a step's JSON result and content-addressed files."""

    def __init__(self, root: Path) -> None:
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
                for relative, digest in stored.items():
                    if not isinstance(relative, str) or not isinstance(digest, str):
                        continue
                    dest = restore_into / relative
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
            for relative, src in files.items():
                digest = _file_digest(src)
                dest = self._blob_path(digest)
                if not dest.is_file():
                    _copy_atomic(src, dest)
                mapping[relative] = digest
        _write_json_atomic(self._entry_path(key), {"value": value, "files": mapping})
