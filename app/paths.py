from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = APP_ROOT / "workflows"
WEB_DIR = APP_ROOT / "app" / "web"
RUNS_DIR = APP_ROOT / "runs"
CACHE_DIR = APP_ROOT / "cache"
VENVS_DIR = APP_ROOT / "venvs"
SDK_DIR = APP_ROOT / "sdk"


def is_safe_path_segment(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name:
        return False
    rel = Path(name)
    return not rel.is_absolute() and len(rel.parts) == 1 and rel.parts[0] not in {".", ".."}


def safe_join(folder: Path, relative: str) -> Path | None:
    rel = Path(relative)
    if rel.is_absolute() or rel.anchor or ".." in rel.parts:
        return None
    return folder / rel
