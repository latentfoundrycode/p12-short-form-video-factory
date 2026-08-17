from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.paths import SDK_DIR, VENVS_DIR, is_safe_path_segment

HASH_MARKER = ".requirements.sha256"


@dataclass(frozen=True)
class EnvReady:
    python: Path


@dataclass(frozen=True)
class EnvBlocked:
    reason: str


type EnvResult = EnvReady | EnvBlocked
type FindPython = Callable[[str], Path | None]
type CreateVenv = Callable[[Path, Path], None]
type Install = Callable[[Path, Path, Path | None], None]


def venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def requirements_hash(workflow_dir: Path) -> str:
    path = workflow_dir / "requirements.txt"
    payload = path.read_bytes() if path.is_file() else b""
    return hashlib.sha256(payload).hexdigest()


def default_find_python(version: str) -> Path | None:
    launcher = shutil.which("py")
    if launcher is not None:
        try:
            completed = subprocess.run(
                [launcher, f"-{version}", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except OSError:
            completed = None
        if completed is not None and completed.returncode == 0:
            candidate = Path(completed.stdout.strip())
            if candidate.is_file():
                return candidate
    for name in (f"python{version}", f"python{version}.exe"):
        found = shutil.which(name)
        if found is not None:
            return Path(found)
    return None


def default_create_venv(python: Path, venv_dir: Path) -> None:
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    subprocess.run([str(python), "-m", "venv", str(venv_dir)], check=True)


def default_install(venv_py: Path, sdk_dir: Path, requirements: Path | None) -> None:
    subprocess.run([str(venv_py), "-m", "pip", "install", "-e", str(sdk_dir)], check=True)
    if requirements is not None:
        subprocess.run([str(venv_py), "-m", "pip", "install", "-r", str(requirements)], check=True)


def _read_stored_hash(venv_dir: Path) -> str | None:
    marker = venv_dir / HASH_MARKER
    if not marker.is_file():
        return None
    return marker.read_text(encoding="utf-8").strip()


def ensure_env(
    workflow_id: str,
    workflow_dir: Path,
    python_version: str,
    *,
    venvs_dir: Path | None = None,
    sdk_dir: Path | None = None,
    find_python: FindPython | None = None,
    create_venv: CreateVenv | None = None,
    install: Install | None = None,
) -> EnvResult:
    if not is_safe_path_segment(workflow_id):
        raise ValueError(f"unsafe workflow id: {workflow_id!r}")
    root = venvs_dir or VENVS_DIR
    sdk = sdk_dir or SDK_DIR
    venv_dir = root / workflow_id
    current_hash = requirements_hash(workflow_dir)
    if venv_dir.is_dir() and _read_stored_hash(venv_dir) == current_hash:
        return EnvReady(python=venv_python(venv_dir))

    locate = find_python or default_find_python
    interpreter = locate(python_version)
    if interpreter is None:
        return EnvBlocked(reason=f"Python {python_version} is required but not installed")

    make_venv = create_venv or default_create_venv
    pip_install = install or default_install
    make_venv(interpreter, venv_dir)
    requirements = workflow_dir / "requirements.txt"
    pip_install(
        venv_python(venv_dir),
        sdk,
        requirements if requirements.is_file() else None,
    )
    (venv_dir / HASH_MARKER).write_text(current_hash, encoding="utf-8")
    return EnvReady(python=venv_python(venv_dir))
