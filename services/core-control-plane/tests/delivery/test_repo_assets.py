from __future__ import annotations

from pathlib import Path

import pytest
from fdai.delivery.repo_assets import repo_asset_root


def _module_at(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_repo_asset_root_resolves_the_installed_image_layout(tmp_path: Path) -> None:
    app = (tmp_path / "app").resolve()
    (app / "rule-catalog").mkdir(parents=True)
    (app / "config").mkdir()
    module = _module_at(app / ".venv/lib/python3.13/site-packages/fdai/delivery/tick.py")

    assert repo_asset_root(module) == app


def test_repo_asset_root_resolves_a_checkout_layout(tmp_path: Path) -> None:
    root = (tmp_path / "repo").resolve()
    (root / "rule-catalog").mkdir(parents=True)
    (root / "config").mkdir()
    module = _module_at(root / "services/core-control-plane/src/fdai/delivery/tick.py")

    assert repo_asset_root(module) == root


def test_repo_asset_root_rejects_a_tree_without_shipped_assets(tmp_path: Path) -> None:
    module = _module_at((tmp_path / "isolated/fdai/delivery/tick.py").resolve())

    with pytest.raises(FileNotFoundError):
        repo_asset_root(module)
