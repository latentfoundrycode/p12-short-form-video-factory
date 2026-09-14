import os
import subprocess
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sfvf.context import BudgetConfig

from app.api.learning import router as learning_router
from app.api.quality import router as quality_router
from app.api.runs import router as runs_router
from app.api.schedules import router as schedules_router
from app.api.statistics import router as statistics_router
from app.api.workflows import RegistryHolder
from app.api.workflows import router as workflows_router
from app.core.budget_config import load_budget_config
from app.core.env import ensure_env as default_ensure_env
from app.core.scheduler_runner import SchedulerDeps, SchedulerDriver, make_scheduler_start
from app.core.schedules import SCHEDULES_PATH
from app.core.secrets import SecretStore, _store_path
from app.core.supervisor import EnsureEnv, PopenFn
from app.paths import RUNS_DIR, WEB_DIR, WORKFLOWS_DIR


def create_app(
    workflows_dir: Path | None = None,
    web_dir: Path | None = None,
    *,
    runs_dir: Path | None = None,
    schedules_path: Path | None = None,
    ensure_env: EnsureEnv | None = None,
    popen: PopenFn | None = None,
    secrets: Mapping[str, str] | None = None,
    budget: BudgetConfig | None = None,
    enable_scheduler: bool = False,
) -> FastAPI:
    if secrets is not None:
        resolved: Mapping[str, str] = secrets
    elif passphrase := os.environ.get("SFVF_SECRETS_PASSPHRASE"):
        resolved = SecretStore(_store_path(), passphrase).all()
    else:
        resolved = {}

    if enable_scheduler:

        @asynccontextmanager
        async def scheduler_lifespan(scheduler_app: FastAPI) -> AsyncIterator[None]:
            holder: RegistryHolder = scheduler_app.state.registry

            def resolve_workflow(workflow_id: str) -> Path | None:
                entry = holder.get(workflow_id)
                if entry is None or any(problem.severity == "error" for problem in entry.problems):
                    return None
                return entry.path

            scheduler_ensure_env: EnsureEnv = scheduler_app.state.ensure_env or default_ensure_env
            scheduler_popen: PopenFn = scheduler_app.state.popen or subprocess.Popen
            scheduler_runs_dir: Path = scheduler_app.state.runs_dir
            scheduler_schedules_path: Path = scheduler_app.state.schedules_path
            scheduler_secrets: Mapping[str, str] = scheduler_app.state.secrets
            scheduler_budget: BudgetConfig | None = scheduler_app.state.budget
            deps = SchedulerDeps(
                resolve_workflow=resolve_workflow,
                runs_dir=scheduler_runs_dir,
                ensure_env=scheduler_ensure_env,
                popen=scheduler_popen,
                secrets=scheduler_secrets,
                budget=scheduler_budget,
            )
            driver = SchedulerDriver(
                schedules_path=scheduler_schedules_path,
                start=make_scheduler_start(deps),
            )
            scheduler_app.state.scheduler_driver = driver
            driver.start()
            try:
                yield
            finally:
                driver.stop()

        application = FastAPI(title="Short-Form Video Factory", lifespan=scheduler_lifespan)
    else:
        application = FastAPI(title="Short-Form Video Factory")
    application.state.registry = RegistryHolder(workflows_dir or WORKFLOWS_DIR)
    application.state.runs_dir = runs_dir or RUNS_DIR
    application.state.schedules_path = schedules_path or SCHEDULES_PATH
    application.state.ensure_env = ensure_env
    application.state.popen = popen
    application.state.secrets = dict(resolved)
    application.state.budget = budget if budget is not None else load_budget_config()
    application.include_router(workflows_router)
    application.include_router(runs_router)
    application.include_router(quality_router)
    application.include_router(learning_router)
    application.include_router(statistics_router)
    application.include_router(schedules_router)

    @application.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    static_root = web_dir or WEB_DIR
    if (static_root / "index.html").is_file():
        application.mount("/", StaticFiles(directory=static_root, html=True), name="web")

    return application


app = create_app(enable_scheduler=os.environ.get("SFVF_ENABLE_SCHEDULER") == "1")
