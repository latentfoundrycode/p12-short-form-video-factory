"""Contract: CSRF guard for state-changing requests (H47).

This is a local single-owner web app with no auth. A page on another website the owner visits can
make their browser fire state-changing requests at `http://localhost:<port>/api/...` (launch/stop/
delete runs, accept learning edits, …) carrying the owner's session — classic drive-by CSRF.
Browsers stamp every fetch/form submission with a `Sec-Fetch-Site` header the page's own JavaScript
CANNOT forge (it is a forbidden header), so it is a reliable origin signal.

The guard runs as middleware on EVERY request: for a state-changing method (anything other than the
safe GET/HEAD/OPTIONS/TRACE), a `Sec-Fetch-Site` of `cross-site` or `same-site` is refused with 403.
`same-origin` (the app's own frontend, served from the same origin), `none` (a direct user
navigation), and an ABSENT header (a non-browser client such as curl or the test suite — not the
CSRF vector) all pass. Safe methods are never guarded (reads are not state-changing, and OPTIONS is
the CORS preflight). One control point protects every current and future mutating route.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    return TestClient(create_app(workflows_dir=workflows, runs_dir=tmp_path / "runs"))


def test_cross_site_mutation_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/api/workflows/rescan", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_same_site_mutation_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/api/workflows/rescan", headers={"Sec-Fetch-Site": "same-site"})
    assert response.status_code == 403


def test_same_origin_mutation_is_allowed(tmp_path: Path) -> None:
    # The app's own frontend fetches carry same-origin and must pass through to the endpoint.
    client = _client(tmp_path)
    response = client.post("/api/workflows/rescan", headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200


def test_missing_fetch_site_is_allowed(tmp_path: Path) -> None:
    # Non-browser clients (curl, the test suite) do not send the header and are not the CSRF vector.
    client = _client(tmp_path)
    response = client.post("/api/workflows/rescan")
    assert response.status_code == 200


def test_none_fetch_site_is_allowed(tmp_path: Path) -> None:
    # `none` = a direct user navigation / address-bar action, not a cross-site fetch.
    client = _client(tmp_path)
    response = client.post("/api/workflows/rescan", headers={"Sec-Fetch-Site": "none"})
    assert response.status_code == 200


def test_safe_get_is_never_guarded(tmp_path: Path) -> None:
    # Reads are not state-changing; a cross-site GET is not blocked.
    client = _client(tmp_path)
    response = client.get("/api/workflows", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200


def test_options_preflight_is_not_blocked(tmp_path: Path) -> None:
    # OPTIONS is a safe method (the CORS preflight) and must never be 403'd by the guard.
    client = _client(tmp_path)
    response = client.options("/api/workflows/rescan", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code != 403


def test_guard_covers_put_and_delete_before_routing(tmp_path: Path) -> None:
    # The guard runs before routing, so a cross-site PUT/DELETE is refused regardless of the path —
    # this covers every mutating route (learning PUT, run DELETE, schedule DELETE, …) at once.
    client = _client(tmp_path)
    for method in (client.put, client.delete):
        response = method("/api/anything", headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403
