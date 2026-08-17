from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.workflows import RegistryHolder
from app.api.workflows import router as workflows_router
from app.paths import WEB_DIR, WORKFLOWS_DIR


def create_app(workflows_dir: Path | None = None, web_dir: Path | None = None) -> FastAPI:
    application = FastAPI(title="Short-Form Video Factory")
    application.state.registry = RegistryHolder(workflows_dir or WORKFLOWS_DIR)
    application.include_router(workflows_router)

    @application.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    static_root = web_dir or WEB_DIR
    if (static_root / "index.html").is_file():
        application.mount("/", StaticFiles(directory=static_root, html=True), name="web")

    return application


app = create_app()
