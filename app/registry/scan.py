from pathlib import Path

from app.registry.problems import Problem, ProblemCode
from app.registry.validate import WorkflowEntry, validate


def scan(workflows_dir: Path) -> list[WorkflowEntry]:
    if not workflows_dir.is_dir():
        return []
    entries: list[WorkflowEntry] = []
    found = sorted(workflows_dir.glob("*/workflow.toml"), key=lambda path: path.parent.name)
    for toml_path in found:
        folder = toml_path.parent
        try:
            entries.append(validate(folder))
        except Exception as exc:
            entries.append(
                WorkflowEntry(
                    folder_name=folder.name,
                    path=folder,
                    manifest=None,
                    problems=(
                        Problem(
                            code=ProblemCode.MANIFEST_UNREADABLE,
                            message=f"{type(exc).__name__}: {exc}",
                            severity="error",
                        ),
                    ),
                )
            )
    return entries
