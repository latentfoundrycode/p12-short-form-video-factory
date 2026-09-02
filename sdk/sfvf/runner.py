from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
import tomllib
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from ._runtime import reset_active, set_active
from .context import Context, ContextFile
from .emit import emit

type EntryField = Literal["entrypoint", "prepare"]


class _EntryFailedError(RuntimeError):
    def __init__(self, message: str, trace: str) -> None:
        super().__init__(message)
        self.trace = trace


def _parse_file_function(spec: str) -> tuple[str, str] | None:
    # Mirrored from app.registry.validate._parse_file_function.
    # sdk/sfvf runs inside the isolated workflow venv and must not import app.
    if spec.count(":") != 1:
        return None
    file_part, function = spec.split(":")
    if not file_part or not function:
        return None
    rel = Path(file_part)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return file_part, function


def _safe_join(folder: Path, relative: str) -> Path | None:
    # Mirrored from app.paths.safe_join. Same process-boundary reason as _parse_file_function.
    rel = Path(relative)
    if rel.is_absolute() or rel.anchor or ".." in rel.parts:
        return None
    return folder / rel


def _load_context(path: Path) -> ContextFile:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"could not read context file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"context file is not valid JSON: {path}") from exc
    try:
        return ContextFile.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(f"context file is invalid: {exc}") from exc


def _function_spec(workflow_dir: Path, field: EntryField) -> str:
    manifest_path = workflow_dir / "workflow.toml"
    try:
        with manifest_path.open("rb") as handle:
            manifest = tomllib.load(handle)
    except OSError as exc:
        raise RuntimeError(f"could not read {manifest_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"workflow.toml is not valid TOML: {manifest_path}") from exc
    section = manifest.get("workflow")
    if not isinstance(section, dict):
        raise RuntimeError("workflow.toml is missing [workflow]")
    value = section.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"workflow.toml does not declare workflow.{field}")
    return value


def _load_function(workflow_dir: Path, spec: str) -> Callable[..., Any]:
    parsed = _parse_file_function(spec)
    if parsed is None:
        raise RuntimeError(f"entrypoint {spec!r} is not a confined file:function")
    file_part, function_name = parsed
    relative = file_part if file_part.endswith(".py") else f"{file_part}.py"
    path = _safe_join(workflow_dir, relative)
    if path is None or not path.is_file():
        raise RuntimeError(f"entrypoint file {file_part!r} was not found")
    module_spec = importlib.util.spec_from_file_location("sfvf_workflow_entrypoint", path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"could not import entrypoint {spec!r}")
    module = importlib.util.module_from_spec(module_spec)
    try:
        module_spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(f"could not import entrypoint {spec!r}: {exc}") from exc
    func = getattr(module, function_name, None)
    if not callable(func):
        raise RuntimeError(f"entrypoint function {function_name!r} was not found in {path.name}")
    return cast(Callable[..., Any], func)


def _write_result(path: Path, value: dict[str, Any] | None) -> None:
    # Atomic replace, mirrored from app.core.records.write_json_atomic.
    # The runner runs in the workflow venv and must not import app.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _capture_return(returned: object) -> dict[str, Any] | None:
    if returned is None:
        return None
    if not isinstance(returned, dict):
        raise RuntimeError("entry must return a JSON object or None")
    try:
        json.dumps(returned)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"entry return value is not JSON-serialisable: {exc}") from exc
    return cast(dict[str, Any], returned)


def _run(
    workflow_dir: Path,
    context_path: Path,
    *,
    entry: EntryField,
    result_path: Path | None,
) -> None:
    data = _load_context(context_path)
    spec = _function_spec(workflow_dir.resolve(), entry)
    func = _load_function(workflow_dir.resolve(), spec)
    ctx = Context(data)
    token = set_active(ctx)
    try:
        returned = func(ctx)
    except Exception as exc:
        raise _EntryFailedError(f"{entry} failed: {exc}", traceback.format_exc()) from exc
    finally:
        reset_active(token)
    if result_path is not None:
        _write_result(result_path, _capture_return(returned))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sfvf.runner")
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument(
        "--entry",
        choices=("entrypoint", "prepare"),
        default="entrypoint",
    )
    parser.add_argument("--result", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        _run(args.workflow, args.context, entry=args.entry, result_path=args.result)
    except Exception as exc:
        event: dict[str, Any] = {"t": "log", "level": "error", "msg": str(exc)}
        if isinstance(exc, _EntryFailedError):
            event["trace"] = exc.trace
        emit(event)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
