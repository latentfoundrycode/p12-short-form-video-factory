from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

WORKFLOW_FIELDS = {
    "id",
    "name",
    "description",
    "thumbnail_url",
    "valid",
    "problems",
    "quality_factors",
    "params",
}

PARAM_FIELDS = {
    "key",
    "type",
    "label",
    "required",
    "default",
    "help",
    "affects_cost",
    "min",
    "max",
    "step",
    "options",
    "options_from",
    "placeholder",
    "unit",
}

PARAMS_TOML = (
    '[[params]]\nkey = "topic"\ntype = "text"\nlabel = "Topic"\nrequired = false\n'
    'help = "Leave empty to let the agent choose."\n\n'
    '[[params]]\nkey = "duration_s"\ntype = "number"\nlabel = "Duration (seconds)"\n'
    'default = 30\naffects_cost = true\nmin = 10\nmax = 90\nstep = 5\nunit = "s"\n\n'
    '[[params]]\nkey = "voice"\ntype = "select"\nlabel = "Narrator voice"\n'
    'default = "narrator"\noptions = ["narrator", "casual"]'
)

QUALITY_FACTORS_TOML = (
    '[[quality_factors]]\nkey = "hook"\nquestion = "Did the first two seconds hook you? Why?"\n\n'
    '[[quality_factors]]\nkey = "pace"\nquestion = "Did the pace hold? Where did it sag?"'
)


def client_for(workflows_dir: Path) -> TestClient:
    return TestClient(create_app(workflows_dir))


def test_list_returns_envelope_in_folder_name_order(tmp_path: Path) -> None:
    write_plugin(tmp_path, "zeta", minimal_toml("zeta"))
    write_plugin(tmp_path, "alpha", minimal_toml("alpha"))
    response = client_for(tmp_path).get("/api/workflows")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"workflows"}
    ids = [item["id"] for item in body["workflows"]]
    assert ids == ["alpha", "zeta"]
    for item in body["workflows"]:
        assert set(item) == WORKFLOW_FIELDS


def test_valid_workflow_serializes_manifest_fields(tmp_path: Path) -> None:
    toml = minimal_toml(
        "news-explainer",
        extra='description = "A 45-second explainer."\nthumbnail = "thumbnail.png"',
    )
    write_plugin(
        tmp_path,
        "news-explainer",
        toml,
        extra_files={"thumbnail.png": "png-bytes"},
    )
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    assert item["id"] == "news-explainer"
    assert item["name"] == "News Explainer"
    assert item["description"] == "A 45-second explainer."
    assert item["thumbnail_url"] == "/api/workflows/news-explainer/thumbnail"
    assert item["valid"] is True
    assert item["problems"] == []
    assert item["quality_factors"] == []


def test_declared_quality_factors_are_exposed(tmp_path: Path) -> None:
    write_plugin(tmp_path, "explainer", minimal_toml("explainer", extra=QUALITY_FACTORS_TOML))
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    assert item["quality_factors"] == [
        {"key": "hook", "question": "Did the first two seconds hook you? Why?"},
        {"key": "pace", "question": "Did the pace hold? Where did it sag?"},
    ]


def test_declared_params_are_exposed_with_defaults(tmp_path: Path) -> None:
    # §8.2 launcher: the API exposes each declared [[params]] so the frontend can render a typed
    # form (labels, types, declared defaults, help, and select options) instead of raw JSON. The
    # declared default is what the launcher pre-fills, so a required-by-the-workflow param like
    # duration_s is never silently missing.
    write_plugin(tmp_path, "explainer", minimal_toml("explainer", extra=PARAMS_TOML))
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    params = item["params"]
    assert [p["key"] for p in params] == ["topic", "duration_s", "voice"]  # declaration order
    assert all(set(p) == PARAM_FIELDS for p in params)
    topic, duration, voice = params
    assert topic["type"] == "text" and topic["default"] is None
    assert topic["help"] == "Leave empty to let the agent choose."
    assert duration["type"] == "number" and duration["default"] == 30
    assert duration["affects_cost"] is True
    assert duration["min"] == 10 and duration["max"] == 90 and duration["step"] == 5
    assert duration["unit"] == "s"
    assert voice["type"] == "select" and voice["default"] == "narrator"
    assert voice["options"] == ["narrator", "casual"]


def test_workflow_without_params_has_empty_params(tmp_path: Path) -> None:
    write_plugin(tmp_path, "explainer", minimal_toml("explainer"))
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    assert item["params"] == []


def test_broken_workflow_has_empty_params(tmp_path: Path) -> None:
    write_plugin(tmp_path, "broken", "[[[not toml")
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    assert item["params"] == []


def test_broken_workflow_has_empty_quality_factors(tmp_path: Path) -> None:
    write_plugin(tmp_path, "broken", "[[[not toml")
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    assert item["quality_factors"] == []


def test_broken_folder_appears_with_folder_id_and_unreadable_problem(tmp_path: Path) -> None:
    write_plugin(tmp_path, "broken-workflow", "[[[not toml")
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    assert item["id"] == "broken-workflow"
    assert item["name"] is None
    assert item["description"] is None
    assert item["thumbnail_url"] is None
    assert item["valid"] is False
    assert any(problem["code"] == "manifest_unreadable" for problem in item["problems"])
    assert all(set(problem) == {"code", "message", "severity"} for problem in item["problems"])


def test_sdk_mismatch_is_valid_with_warning(tmp_path: Path) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml().replace('sdk = "1"', 'sdk = "2"'))
    item = client_for(tmp_path).get("/api/workflows").json()["workflows"][0]
    assert item["valid"] is True
    warnings = [p for p in item["problems"] if p["code"] == "sdk_version_mismatch"]
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "warning"


def test_rescan_picks_up_folder_added_after_snapshot(tmp_path: Path) -> None:
    write_plugin(tmp_path, "alpha", minimal_toml("alpha"))
    client = client_for(tmp_path)
    assert [item["id"] for item in client.get("/api/workflows").json()["workflows"]] == ["alpha"]

    write_plugin(tmp_path, "beta", minimal_toml("beta"))
    assert [item["id"] for item in client.get("/api/workflows").json()["workflows"]] == ["alpha"]

    rescan = client.post("/api/workflows/rescan")
    assert rescan.status_code == 200
    assert [item["id"] for item in rescan.json()["workflows"]] == ["alpha", "beta"]
    assert [item["id"] for item in client.get("/api/workflows").json()["workflows"]] == [
        "alpha",
        "beta",
    ]


def test_thumbnail_declared_and_present_returns_image(tmp_path: Path) -> None:
    write_plugin(
        tmp_path,
        "news-explainer",
        minimal_toml(extra='thumbnail = "thumbnail.png"'),
        extra_files={"thumbnail.png": "png-bytes"},
    )
    response = client_for(tmp_path).get("/api/workflows/news-explainer/thumbnail")
    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert "image/png" in response.headers["content-type"]


def test_thumbnail_declared_but_missing_is_404(tmp_path: Path) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml(extra='thumbnail = "thumbnail.png"'))
    response = client_for(tmp_path).get("/api/workflows/news-explainer/thumbnail")
    assert response.status_code == 404


def test_thumbnail_none_declared_is_404(tmp_path: Path) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml())
    response = client_for(tmp_path).get("/api/workflows/news-explainer/thumbnail")
    assert response.status_code == 404


def test_thumbnail_unknown_id_is_404(tmp_path: Path) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml())
    response = client_for(tmp_path).get("/api/workflows/no-such/thumbnail")
    assert response.status_code == 404


def test_thumbnail_traversal_id_is_rejected(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(tmp_path / "workflows", "news-explainer", minimal_toml())
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"do-not-serve")
    client = client_for(workflows)
    response = client.get("/api/workflows/..%2f..%2fsecret/thumbnail")
    assert response.status_code == 404
    assert b"do-not-serve" not in response.content
