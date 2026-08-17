from __future__ import annotations

import argparse
import importlib.util
import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from .context import Context, ContextFile
from .emit import log


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


def _entrypoint_spec(workflow_dir: Path) -> str:
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
    entrypoint = section.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint:
        raise RuntimeError("workflow.toml is missing workflow.entrypoint")
    return entrypoint


def _load_entrypoint(workflow_dir: Path) -> Callable[..., Any]:
    spec = _entrypoint_spec(workflow_dir)
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


def _run(workflow_dir: Path, context_path: Path) -> None:
    data = _load_context(context_path)
    func = _load_entrypoint(workflow_dir.resolve())
    try:
        func(Context(data))
    except Exception as exc:
        raise RuntimeError(f"entrypoint failed: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sfvf.runner")
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _run(args.workflow, args.context)
    except Exception as exc:
        log(str(exc), level="error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
