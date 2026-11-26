from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "scripts/deployment/system_knowledge/build_teams_app.py"
INSTALL = ROOT / "scripts/deployment/system_knowledge/install_teams_app.py"
APP_ID = "00000000-0000-0000-0000-000000000001"
TEAM_ID = "00000000-0000-0000-0000-000000000002"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_uploads_and_installs_missing_package(tmp_path: Path) -> None:
    builder = _module(BUILD, "build_teams_app_install_test")
    installer = _module(INSTALL, "install_teams_app")
    package = tmp_path / "app.zip"
    builder.build_package(app_id=APP_ID, bot_id=APP_ID, output=package)
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        if request.url.path.endswith("/appCatalogs/teamsApps"):
            return httpx.Response(201, json={"id": "catalog-app"})
        return httpx.Response(201, json={"id": "installation"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = installer.install_package(
            package=package,
            team_id=TEAM_ID,
            access_token="header.payload.signature",
            transport=client,
        )

    assert result == {
        "external_id": APP_ID,
        "catalog_app_id": "catalog-app",
        "uploaded": True,
        "installed": True,
    }
    assert calls == [
        ("GET", "/v1.0/appCatalogs/teamsApps"),
        ("POST", "/v1.0/appCatalogs/teamsApps"),
        ("GET", f"/v1.0/teams/{TEAM_ID}/installedApps"),
        ("POST", f"/v1.0/teams/{TEAM_ID}/installedApps"),
    ]


def test_graph_permission_failure_is_actionable(tmp_path: Path) -> None:
    builder = _module(BUILD, "build_teams_app_permission_test")
    installer = _module(INSTALL, "install_teams_app_permission")
    package = tmp_path / "app.zip"
    builder.build_package(app_id=APP_ID, bot_id=APP_ID, output=package)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": "Forbidden"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(installer.TeamsAppInstallError, match=r"403 \(Forbidden\)"):
            installer.install_package(
                package=package,
                team_id=TEAM_ID,
                access_token="header.payload.signature",
                transport=client,
            )
