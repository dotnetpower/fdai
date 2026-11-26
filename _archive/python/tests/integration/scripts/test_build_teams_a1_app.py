"""Focused tests for the Teams A1 approval-bot app package builder."""

from __future__ import annotations

import importlib.util
import json
import struct
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deployment/azure/build_teams_a1_app.py"
APP_ID = "00000000-0000-0000-0000-000000000011"
BOT_ID = "00000000-0000-0000-0000-000000000012"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("build_teams_a1_app", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _png_size(value: bytes) -> tuple[int, int]:
    assert value.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", value[16:24])


def test_package_is_deterministic_and_approval_only(module, tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    module.build_package(app_id=APP_ID, bot_id=BOT_ID, output=first)
    module.build_package(app_id=APP_ID, bot_id=BOT_ID, output=second)

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {"manifest.json", "color.png", "outline.png"}
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["id"] == APP_ID
        assert manifest["manifestVersion"] == "1.30"
        assert len(manifest["bots"]) == 1
        assert manifest["bots"][0]["botId"] == BOT_ID
        assert manifest["bots"][0]["scopes"] == ["team"]
        assert manifest["bots"][0]["isNotificationOnly"] is False
        assert "authorization" not in manifest
        assert _png_size(archive.read("color.png")) == (192, 192)
        assert _png_size(archive.read("outline.png")) == (32, 32)


def test_package_rejects_noncanonical_identifiers(module, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UUID"):
        module.build_package(app_id="not-a-guid", bot_id=BOT_ID, output=tmp_path / "app.zip")


def test_package_rejects_manifest_outside_approval_contract(module, tmp_path: Path) -> None:
    template = tmp_path / "manifest.template.json"
    template.write_text(
        json.dumps(
            {
                "manifestVersion": "1.30",
                "id": "${TEAMS_APP_ID}",
                "authorization": {"permissions": {"resourceSpecific": []}},
                "bots": [
                    {
                        "botId": "${BOT_APP_ID}",
                        "scopes": ["team"],
                        "isNotificationOnly": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="approval-only bot contract"):
        module.build_package(
            app_id=APP_ID,
            bot_id=BOT_ID,
            output=tmp_path / "app.zip",
            template=template,
        )
