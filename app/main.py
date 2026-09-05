import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.runs import router as runs_router
from app.api.workflows import RegistryHolder
from app.api.workflows import router as workflows_router
from app.core.secrets import SecretStore, _store_path
from app.core.supervisor import EnsureEnv, PopenFn
from app.paths import RUNS_DIR, WEB_DIR, WORKFLOWS_DIR


def create_app(
    workflows_dir: Path | None = None,
    web_dir: Path | None = None,
    *,
    runs_dir: Path | None = None,
    ensure_env: EnsureEnv | None = None,
    popen: PopenFn | None = None,
    secrets: Mapping[str, str] | None = None,
) -> FastAPI:
    if secrets is not None:
        resolved: Mapping[str, str] = secrets
    elif passphrase := os.environ.get("SFVF_SECRETS_PASSPHRASE"):
        resolved = SecretStore(_store_path(), passphrase).all()
    else:
        resolved = {}
    application = FastAPI(title="Short-Form Video Factory")
    application.state.registry = RegistryHolder(workflows_dir or WORKFLOWS_DIR)
    application.state.runs_dir = runs_dir or RUNS_DIR
    application.state.ensure_env = ensure_env
    application.state.popen = popen
    application.state.secrets = dict(resolved)
    application.include_router(workflows_router)
    application.include_router(runs_router)

    @application.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    static_root = web_dir or WEB_DIR
    if (static_root / "index.html").is_file():
        application.mount("/", StaticFiles(directory=static_root, html=True), name="web")

    return application


app = create_app()
