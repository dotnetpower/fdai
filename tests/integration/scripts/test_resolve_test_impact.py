"""Regression tests for static Python test-impact resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.automation.resolve_test_impact import (
    _imports,
    _module_name,
    _resolve_from,
    main,
    resolve_tests,
)


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


def test_module_name_supports_source_roots_and_rejects_resources(tmp_path: Path) -> None:
    assert _module_name(tmp_path / "delivery/gateway/__init__.py", tmp_path) == ("delivery.gateway")
    assert _module_name(tmp_path / "tools/report.py", tmp_path) == "tools.report"
    assert _module_name(tmp_path / "unknown/report.py", tmp_path) is None
    assert _module_name(tmp_path / "src/fdai/schema.json", tmp_path) is None


def test_relative_import_resolution_handles_boundaries() -> None:
    assert _resolve_from("fdai.core.module", "risk_gate", 0, is_package=False) == "risk_gate"
    assert _resolve_from("module", "risk_gate", 1, is_package=False) is None
    assert _resolve_from("fdai.core.module", None, 1, is_package=False) == "fdai.core"


def test_import_parser_handles_absolute_dynamic_and_invalid_files(tmp_path: Path) -> None:
    known = {"fdai.core.risk_gate", "fdai.core.risk_gate.rule"}
    source = _write(
        tmp_path,
        "src/fdai/core/module.py",
        """import fdai.core.risk_gate.rule
from . import risk_gate
importlib.import_module("fdai.core.risk_gate.rule")
print("not an import")
""",
    )
    invalid = _write(tmp_path, "src/fdai/core/invalid.py", "def broken(:\n")

    imports = _imports(source, "fdai.core.module", known)

    assert "fdai.core.risk_gate.rule" in imports
    assert "fdai.core.risk_gate" in imports
    assert _imports(invalid, "fdai.core.invalid", known) == set()


def test_non_source_change_has_no_python_impact(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_example.py", "def test_example(): pass\n")

    assert resolve_tests(tmp_path, [tmp_path / "README.md"]) == []


def test_cli_prints_selected_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    changed = _write(tmp_path, "src/fdai/core/risk_gate/rule.py", "VALUE = 1\n")
    consumer = _write(
        tmp_path,
        "tests/core/risk_gate/test_rule.py",
        "from fdai.core.risk_gate import rule\n",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["resolve_test_impact.py", "--root", str(tmp_path), str(changed)],
    )

    assert main() == 0
    assert capsys.readouterr().out.splitlines() == [consumer.relative_to(tmp_path).as_posix()]
