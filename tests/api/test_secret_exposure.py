"""S2b contract: injected secrets must not be exposed after S2a put them in context.json.

Two vectors closed:
1. The run-file download endpoint must NEVER serve a `context.json` (it carries the allowlisted
   secrets) — any request for one returns 404, while other run files still download.
2. After the workflow subprocess has consumed its `context.json`, the on-disk copy is scrubbed
   (`secrets` emptied) so the keys don't persist in the run directory.

Fake values live only under tmp_path.
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.supervisor as supervisor_mod
from app.core.env import EnvReady
from app.main import create_app

STUBS = Path(__file__).resolve().parent.parent / "stubs"
TERMINAL = {"complete", "partial", "stopped", "stopped-budget", "failed"}


@pytest.fixture(autouse=True)
def _clear_supervisor_state():
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()
    yield
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with supervisor_mod._lock:
            if not supervisor_mod._active and not supervisor_mod._runs:
                break
        time.sleep(0.05)
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _install_stub(
    workflows_dir: Path, name: str, *, requires_keys: list[str] | None = None
) -> None:
    dest = workflows_dir / name
    shutil.copytree(STUBS / name, dest)
    (dest / "requirements.txt").write_text("", encoding="utf-8")
    if requires_keys:
        toml = dest / "workflow.toml"
        extra = "".join(
            f'\n[[requires_keys]]\nname = "{k}"\nlabel = "{k}"\n' for k in requires_keys
        )
        toml.write_text(toml.read_text(encoding="utf-8") + extra, encoding="utf-8")


def _client(tmp_path: Path, *, secrets: object = None, popen: object = None) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    return TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
            secrets=secrets,  # type: ignore[arg-type]
            popen=popen,  # type: ignore[arg-type]
        )
    )


def _wait_terminal(client: TestClient, run_id: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/workflows/succeeds/runs/{run_id}")
        if r.status_code == 200 and r.json()["status"] in TERMINAL:
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach a terminal status")


def test_context_json_is_not_downloadable(tmp_path):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    # A run dir with a context.json (secret-bearing) and an ordinary artifact.
    run_dir = tmp_path / "runs" / "succeeds" / "20260101-000000" / "shared"
    run_dir.mkdir(parents=True)
    (run_dir / "context.json").write_text('{"secrets": {"OPENROUTER_API_KEY": "sk-x"}}', "utf-8")
    (run_dir / "note.txt").write_text("ordinary", "utf-8")

    base = "/api/workflows/succeeds/runs/20260101-000000/files/shared"
    assert client.get(f"{base}/context.json").status_code == 404  # secret file blocked
    assert client.get(f"{base}/note.txt").status_code == 200  # ordinary file still served


def test_shared_result_json_is_not_downloadable(tmp_path):
    # H18: the prepare output at shared/result.json can carry an injected secret in arbitrary
    # bytes/encoding a workflow controls (e.g. UTF-16) that best-effort value redaction cannot fully
    # strip. That SPECIFIC engine-written path must not be served (closing the download exfil vector
    # for every encoding) and is excluded from the listing. The block is PATH-scoped to
    # shared/result.json, so a workflow artifact that only shares the basename is still served. The
    # engine reads shared/result.json from disk directly, not via this endpoint.
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    run_root = tmp_path / "runs" / "succeeds" / "20260101-000000"
    shared = run_root / "shared"
    shared.mkdir(parents=True)
    # a secret encoded as UTF-16 — value redaction that scans UTF-8 bytes would miss it
    (shared / "result.json").write_bytes('{"leaked": "sk-x"}'.encode("utf-16"))
    (shared / "note.txt").write_text("ordinary", "utf-8")
    # a legitimate workflow artifact that merely shares the basename must NOT be blocked
    artifacts = shared / "artifacts"
    artifacts.mkdir()
    (artifacts / "result.json").write_text('{"ok": true}', "utf-8")

    base = "/api/workflows/succeeds/runs/20260101-000000/files"
    assert client.get(f"{base}/shared/result.json").status_code == 404  # the secret-riskable file
    assert client.get(f"{base}/shared/note.txt").status_code == 200  # ordinary file still served
    assert client.get(f"{base}/shared/artifacts/result.json").status_code == 200  # legit artifact
    listing = client.get("/api/workflows/succeeds/runs/20260101-000000/files").json()
    names = [f["path"] for f in listing["files"]]
    assert "shared/result.json" not in names  # the prepare output is excluded, like context.json
    assert "shared/note.txt" in names
    assert "shared/artifacts/result.json" in names  # the legit artifact is still listed


def test_dot_prefixed_run_files_are_not_downloadable(tmp_path):
    # H61: files under a dot-prefixed dir (e.g. shared/.steps/, the step cache) are excluded from
    # the listing but were still fetchable by path via get_run_file. A cached step result could
    # carry a secret, so get_run_file must also refuse any dot-prefixed path part — matching the
    # listing's exclusion so a listing-hidden file cannot be fetched by guessing its path.
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds")
    client = _client(tmp_path)
    run_root = tmp_path / "runs" / "succeeds" / "20260101-000000"
    steps = run_root / "shared" / ".steps"
    steps.mkdir(parents=True)
    (steps / "cache.json").write_text('{"cached": "value"}', "utf-8")
    (run_root / "shared" / "note.txt").write_text("ordinary", "utf-8")

    base = "/api/workflows/succeeds/runs/20260101-000000/files"
    assert client.get(f"{base}/shared/.steps/cache.json").status_code == 404  # dot-dir not served
    assert client.get(f"{base}/shared/note.txt").status_code == 200  # ordinary file still served
    names = [f["path"] for f in client.get(f"{base}").json()["files"]]
    assert not any(part.startswith(".") for name in names for part in name.split("/"))
    assert "shared/note.txt" in names


def test_secrets_scrubbed_even_when_runner_spawn_fails(tmp_path):
    # Even if the runner subprocess fails to spawn, the injected secrets must not linger on disk
    # in context.json (the scrub runs in a finally that wraps the spawn).
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds", requires_keys=["OPENROUTER_API_KEY"])

    def failing_popen(command, **kwargs):
        raise OSError("cannot spawn runner")

    client = _client(
        tmp_path, secrets={"OPENROUTER_API_KEY": "sk-secret-value"}, popen=failing_popen
    )
    r = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "a"}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        found = list((tmp_path / "runs").rglob("context.json"))
        if found and all(
            json.loads(p.read_text(encoding="utf-8")).get("secrets") == {} for p in found
        ):
            break
        time.sleep(0.05)

    contexts = list((tmp_path / "runs").rglob("context.json"))
    assert contexts, "context.json was never written"
    for ctx_path in contexts:
        text = ctx_path.read_text(encoding="utf-8")
        assert json.loads(text).get("secrets") == {}, f"secrets not scrubbed in {ctx_path}"
        assert "sk-secret-value" not in text


def test_context_json_secrets_are_scrubbed_after_run(tmp_path):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    _install_stub(workflows_dir, "succeeds", requires_keys=["OPENROUTER_API_KEY"])
    client = _client(tmp_path, secrets={"OPENROUTER_API_KEY": "sk-secret-value"})
    r = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "a"}, "video_count": 1, "concurrency": 1},
    )
    assert r.status_code == 202
    _wait_terminal(client, r.json()["run_id"])

    contexts = list((tmp_path / "runs").rglob("context.json"))
    assert contexts, "no context.json was written"
    for ctx_path in contexts:
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert data.get("secrets") == {}, f"secrets not scrubbed in {ctx_path}"
        # and the raw value is gone from disk
        assert "sk-secret-value" not in ctx_path.read_text(encoding="utf-8")
