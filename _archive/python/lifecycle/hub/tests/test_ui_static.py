"""Static serving of the built operator UI (`fdai_lifecycle_hub.api.create_app`'s `static_dir`)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.store import HubStore


@pytest.fixture
def built_ui(tmp_path: Path) -> Path:
    """A minimal stand-in for `ui/dist/`: an index, a built asset, and a public asset."""

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('ui');")
    (tmp_path / "brand").mkdir()
    (tmp_path / "brand" / "fdai-logo.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (tmp_path / "index.html").write_text("<html><body>shell</body></html>")
    return tmp_path


@pytest.fixture
def ui_client(store: HubStore, built_ui: Path, now: datetime) -> TestClient:
    return TestClient(create_app(store, clock=lambda: now, static_dir=built_ui))


def test_root_serves_the_shell(ui_client: TestClient) -> None:
    response = ui_client.get("/")

    assert response.status_code == 200
    assert "shell" in response.text


def test_a_built_asset_is_served_as_itself(ui_client: TestClient) -> None:
    response = ui_client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == "console.log('ui');"


def test_a_public_asset_outside_the_assets_directory_is_served_as_itself(
    ui_client: TestClient,
) -> None:
    """Regression: the brand logo under `ui/public/brand/` once fell through to `index.html`
    because the route only mounted `assets/` as static content."""

    response = ui_client.get("/brand/fdai-logo.png")

    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n\x1a\nfake"


def test_an_spa_route_without_a_matching_file_falls_back_to_the_shell(
    ui_client: TestClient,
) -> None:
    response = ui_client.get("/installations/example")

    assert response.status_code == 200
    assert "shell" in response.text
