"""Report format boundary gate."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/quality/architecture/check-report-format-boundary.py"
FORMATS = Path("services/core-control-plane/src/fdai/core/reporting/formats")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_report_format_boundary", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    target = tmp_path / FORMATS
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / FORMATS, target, ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def test_shipped_formats_pass() -> None:
    assert checker.validate(REPO_ROOT) == []


def test_unregistered_encoder_is_rejected(workspace: Path) -> None:
    (workspace / FORMATS / "yaml_format.py").write_text(
        "class YamlFormatEncoder:\n    pass\n", encoding="utf-8"
    )

    errors = checker.validate(workspace)

    assert any("not exported" in error for error in errors)
    assert any("neither registered nor documented" in error for error in errors)


def test_delivery_dependency_in_a_format_module_is_rejected(workspace: Path) -> None:
    path = workspace / FORMATS / "json_format.py"
    path.write_text("import reportlab\n" + path.read_text(encoding="utf-8"), encoding="utf-8")

    errors = checker.validate(workspace)

    assert any("forbidden import 'reportlab'" in error for error in errors)


def test_module_without_exactly_one_encoder_is_rejected(workspace: Path) -> None:
    (workspace / FORMATS / "pair_format.py").write_text(
        "class OneFormatEncoder:\n    pass\n\n\nclass TwoFormatEncoder:\n    pass\n",
        encoding="utf-8",
    )

    errors = checker.validate(workspace)

    assert any("expected exactly one *FormatEncoder class, found 2" in error for error in errors)


def test_missing_formats_directory_is_reported(tmp_path: Path) -> None:
    assert checker.validate(tmp_path) == [f"{FORMATS.as_posix()}: directory is missing"]
