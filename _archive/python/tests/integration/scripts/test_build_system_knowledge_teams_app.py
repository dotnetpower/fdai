from __future__ import annotations

import importlib.util
import json
import struct
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deployment/system_knowledge/build_teams_app.py"
APP_ID = "00000000-0000-0000-0000-000000000001"
BOT_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("build_system_knowledge_teams_app", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _png_size(value: bytes) -> tuple[int, int]:
    assert value.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", value[16:24])


def test_package_is_deterministic_and_mention_only(module, tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    module.build_package(app_id=APP_ID, bot_id=BOT_ID, output=first)
    module.build_package(app_id=APP_ID, bot_id=BOT_ID, output=second)

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {"manifest.json", "color.png", "outline.png"}
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["id"] == APP_ID
        assert manifest["bots"][0]["botId"] == BOT_ID
        assert manifest["bots"][0]["scopes"] == ["team"]
        assert "authorization" not in manifest
        assert _png_size(archive.read("color.png")) == (192, 192)
        assert _png_size(archive.read("outline.png")) == (32, 32)


def test_package_rejects_noncanonical_identifiers(module, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UUID"):
        module.build_package(app_id="not-a-guid", bot_id=BOT_ID, output=tmp_path / "app.zip")
