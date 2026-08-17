from pathlib import Path

from app.registry.validate import WorkflowEntry


def minimal_toml(workflow_id: str = "news-explainer", extra: str = "") -> str:
    return f"""
[workflow]
id = "{workflow_id}"
name = "News Explainer"
version = "1.0.0"
entrypoint = "main:run"
sdk = "1"
{extra}
"""


def write_plugin(
    parent: Path,
    folder_name: str,
    toml: str,
    *,
    main_py: bool = True,
    requirements: bool = True,
    extra_files: dict[str, str] | None = None,
) -> Path:
    folder = parent / folder_name
    folder.mkdir(parents=True)
    (folder / "workflow.toml").write_text(toml.strip() + "\n", encoding="utf-8")
    if main_py:
        (folder / "main.py").write_text("# fixture\n", encoding="utf-8")
    if requirements:
        (folder / "requirements.txt").write_text("", encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return folder


def problem_codes(entry: WorkflowEntry) -> set[str]:
    return {problem.code.value for problem in entry.problems}
