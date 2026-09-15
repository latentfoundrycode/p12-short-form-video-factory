from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class AcceptError(Exception):
    pass


@dataclass(frozen=True)
class AcceptResult:
    applied: list[str]


_FRONTMATTER = re.compile(
    r"\A---\n(?P<body>.*?)(?P<closing>^---(?:\n|\Z))",
    re.DOTALL | re.MULTILINE,
)
_VERSION = re.compile(r"^version:\s*(\d+)[ \t]*$", re.MULTILINE)


def _read_version(text: str) -> int:
    frontmatter = _FRONTMATTER.match(text)
    if frontmatter is None:
        return 1
    version = _VERSION.search(frontmatter.group("body"))
    return int(version.group(1)) if version is not None else 1


def _set_version(text: str, version: int) -> str:
    frontmatter = _FRONTMATTER.match(text)
    if frontmatter is None:
        return f"---\nversion: {version}\n---\n{text}"

    version_line = _VERSION.search(frontmatter.group("body"))
    if version_line is None:
        body_start = frontmatter.start("body")
        return f"{text[:body_start]}version: {version}\n{text[body_start:]}"

    start = frontmatter.start("body") + version_line.start()
    end = frontmatter.start("body") + version_line.end()
    return f"{text[:start]}version: {version}{text[end:]}"


def _valid_staged_path(raw_path: str) -> bool:
    if "\\" in raw_path or ":" in raw_path:
        return False
    path = PurePosixPath(raw_path)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) >= 2
        and path.parts[0] in {"rules", "skills"}
    )


def apply_instruction_edit(workflow_dir: Path, relative_path: str, content: str) -> int:
    """Archive the current live file (if any) keyed by its version, write `content` to the live
    path with frontmatter `version` set to prior+1 (a new file starts at 1), and return the new
    version. `relative_path` must be a workflow-relative POSIX path under rules/ or skills/;
    anything else raises AcceptError. The caller holds the per-workflow lock."""
    if not _valid_staged_path(relative_path):
        raise AcceptError(f"staged path is outside rules/ and skills/: {relative_path}")

    relative = PurePosixPath(relative_path)
    root = workflow_dir.resolve()
    live = workflow_dir.joinpath(*relative.parts)
    if not live.resolve().is_relative_to(root):
        raise AcceptError(f"live path escapes workflow directory: {relative_path}")
    if live.is_file():
        old_version = _read_version(live.read_text(encoding="utf-8"))
        archive_name = f"{relative.stem}.v{old_version}{relative.suffix}"
        archive = workflow_dir.joinpath("archive", *relative.with_name(archive_name).parts)
        if not archive.resolve().is_relative_to(root):
            raise AcceptError(f"archive path escapes workflow directory: {relative_path}")
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(live, archive)
        new_version = old_version + 1
    else:
        new_version = 1

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    written = _set_version(content, new_version)
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(written, encoding="utf-8", newline="\n")
    return new_version


def accept_learning(workflow_dir: Path, staging_dir: Path) -> AcceptResult:
    workflow = workflow_dir.resolve()
    staging = staging_dir.resolve()
    if workflow == staging or workflow.is_relative_to(staging) or staging.is_relative_to(workflow):
        raise AcceptError("staging directory must not overlap workflow directory")

    staged = sorted(
        (path.relative_to(staging_dir).as_posix(), path)
        for path in staging_dir.rglob("*")
        if path.is_file()
    )

    for relative_path, _ in staged:
        if not _valid_staged_path(relative_path):
            raise AcceptError(f"staged path is outside rules/ and skills/: {relative_path}")

    for relative_path, staged_file in staged:
        apply_instruction_edit(
            workflow_dir,
            relative_path,
            staged_file.read_text(encoding="utf-8"),
        )

    shutil.rmtree(staging_dir, ignore_errors=True)
    return AcceptResult(applied=[relative_path for relative_path, _ in staged])


def reject_learning(staging_dir: Path) -> None:
    shutil.rmtree(staging_dir, ignore_errors=True)
