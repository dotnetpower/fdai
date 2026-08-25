from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/azure/build_dev_gateway_artifact.py"
_SPEC = importlib.util.spec_from_file_location("build_dev_gateway_artifact", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build = _MODULE.build

_REQUIRED = ("function_app.py", "gateway.py", "host.json", "requirements.txt")


def test_builder_includes_only_runtime_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for name in _REQUIRED:
        (source / name).write_text(name, encoding="utf-8")
    (source / "README.md").write_text("docs", encoding="utf-8")
    (source / ".funcignore").write_text("ignored", encoding="utf-8")
    cache = source / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"cache")

    names = build(source, tmp_path / "gateway.zip")

    assert names == tuple(sorted(_REQUIRED))


def test_builder_removes_incomplete_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "function_app.py").write_text("app", encoding="utf-8")
    target = tmp_path / "gateway.zip"

    with pytest.raises(ValueError, match="artifact is missing"):
        build(source, target)

    assert not target.exists()


def test_builder_requires_source_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source directory is unavailable"):
        build(tmp_path / "missing", tmp_path / "gateway.zip")
