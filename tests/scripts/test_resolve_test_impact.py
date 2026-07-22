"""Regression tests for static Python test-impact resolution."""

from __future__ import annotations

from pathlib import Path

from scripts.automation.resolve_test_impact import resolve_tests


def _write(root: Path, relative: str, content: str = "\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_resolves_direct_and_transitive_consumers(tmp_path: Path) -> None:
    changed = _write(tmp_path, "src/fdai/core/risk_gate/rule.py", "VALUE = 1\n")
    _write(
        tmp_path,
        "src/fdai/core/service.py",
        "from fdai.core.risk_gate import rule\n",
    )
    direct = _write(
        tmp_path,
        "tests/core/risk_gate/test_rule.py",
        "from fdai.core.risk_gate import rule\n",
    )
    transitive = _write(
        tmp_path,
        "tests/pipeline/test_service.py",
        "from fdai.core import service\n",
    )

    assert resolve_tests(tmp_path, [changed]) == [
        direct.relative_to(tmp_path),
        transitive.relative_to(tmp_path),
    ]


def test_resolves_package_reexport_consumer(tmp_path: Path) -> None:
    changed = _write(tmp_path, "src/fdai/core/risk_gate/rule.py", "VALUE = 1\n")
    _write(
        tmp_path,
        "src/fdai/core/risk_gate/__init__.py",
        "from .rule import VALUE\n",
    )
    consumer = _write(
        tmp_path,
        "tests/pipeline/test_rule.py",
        "from fdai.core import risk_gate\n",
    )

    assert resolve_tests(tmp_path, [changed]) == [consumer.relative_to(tmp_path)]


def test_package_initializer_change_selects_descendant_import(tmp_path: Path) -> None:
    changed = _write(tmp_path, "src/fdai/core/__init__.py")
    _write(tmp_path, "src/fdai/core/risk_gate/rule.py", "VALUE = 1\n")
    consumer = _write(
        tmp_path,
        "tests/pipeline/test_rule.py",
        "from fdai.core.risk_gate import rule\n",
    )

    assert resolve_tests(tmp_path, [changed]) == [consumer.relative_to(tmp_path)]


def test_dynamic_import_prefix_selects_layout_consumer(tmp_path: Path) -> None:
    changed = _write(tmp_path, "src/fdai/core/risk_gate/rule.py", "VALUE = 1\n")
    consumer = _write(
        tmp_path,
        "tests/core/test_layout.py",
        'import importlib\nname = "risk_gate"\nimportlib.import_module(f"fdai.core.{name}")\n',
    )

    assert resolve_tests(tmp_path, [changed]) == [consumer.relative_to(tmp_path)]


def test_resolves_consumer_of_deleted_module(tmp_path: Path) -> None:
    consumer = _write(
        tmp_path,
        "tests/pipeline/test_removed.py",
        "from fdai.core.risk_gate import removed\n",
    )
    deleted = tmp_path / "src/fdai/core/risk_gate/removed.py"

    assert resolve_tests(tmp_path, [deleted]) == [consumer.relative_to(tmp_path)]
