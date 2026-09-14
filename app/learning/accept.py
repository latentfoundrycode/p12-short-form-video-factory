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
        relative = PurePosixPath(relative_path)
        live = workflow_dir.joinpath(*relative.parts)
        if live.is_file():
            old_version = _read_version(live.read_text(encoding="utf-8"))
            archive_name = f"{relative.stem}.v{old_version}{relative.suffix}"
            archive = workflow_dir.joinpath("archive", *relative.with_name(archive_name).parts)
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(live, archive)
            new_version = old_version + 1
        else:
            new_version = 1

        content = _set_version(
            staged_file.read_text(encoding="utf-8"),
            new_version,
        )
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text(content, encoding="utf-8", newline="\n")

    shutil.rmtree(staging_dir, ignore_errors=True)
    return AcceptResult(applied=[relative_path for relative_path, _ in staged])


def reject_learning(staging_dir: Path) -> None:
    shutil.rmtree(staging_dir, ignore_errors=True)
