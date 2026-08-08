"""Regression tests for the evaluation architecture boundary gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_GATE = _ROOT / "scripts" / "quality" / "architecture" / "check-evaluation-boundaries.py"


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, str(_GATE), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_public_dependency_direction_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "services/core-control-plane/src/fdai/evaluation/host.py",
        "from fdai_evaluation_sdk import EvaluationTask\n",
    )
    _write(
        tmp_path,
        "evaluation-sdk/src/fdai_evaluation_sdk/api.py",
        "from typing import Protocol\n",
    )
    _write(
        tmp_path,
        "benchmarks/example/src/fdai_bench_example/adapter.py",
        "from fdai_evaluation_sdk import EvaluationTask\n",
    )
    assert _run(tmp_path).returncode == 0


@pytest.mark.parametrize(
    ("relative", "source", "message"),
    (
        (
            "services/core-control-plane/src/fdai/evaluation/host.py",
            "import fdai_bench_example\n",
            "MUST NOT import benchmark",
        ),
        (
            "evaluation-sdk/src/fdai_evaluation_sdk/api.py",
            "from fdai.core import control_loop\n",
            "SDK MUST NOT import FDAI",
        ),
        (
            "benchmarks/example/src/fdai_bench_example/adapter.py",
            "from fdai.runtime import control_loop\n",
            "private FDAI",
        ),
        (
            "benchmarks/example/src/fdai_bench_example/adapter.py",
            "import subprocess\nsubprocess.run(['sh'])\n",
            "reviewed provider",
        ),
        (
            "benchmarks/example/src/fdai_bench_example/adapter.py",
            "MetadataEntry(key='payload', value=b'binary')\n",
            "MUST NOT enter metadata",
        ),
    ),
)
def test_violation_is_blocked(
    tmp_path: Path,
    relative: str,
    source: str,
    message: str,
) -> None:
    _write(tmp_path, relative, source)
    result = _run(tmp_path)
    assert result.returncode == 1
    assert message in result.stdout


def test_benchmark_may_import_only_public_fdai_spi(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "benchmarks/example/src/fdai_bench_example/adapter.py",
        "from fdai.evaluation.public import EvaluationHost\n",
    )
    assert _run(tmp_path).returncode == 0


def test_newer_non_evaluation_fdai_syntax_uses_import_fallback(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "services/core-control-plane/src/fdai/core/new_syntax.py",
        "def identity[T](value: T) -> T:\n    return value\n",
    )
    assert _run(tmp_path).returncode == 0

    _write(
        tmp_path,
        "services/core-control-plane/src/fdai/core/new_syntax.py",
        "from fdai_bench_example import Adapter\n"
        "def identity[T](value: T) -> T:\n    return value\n",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "MUST NOT import benchmark" in result.stdout


def test_newer_sdk_syntax_uses_dependency_fallback(tmp_path: Path) -> None:
    path = "evaluation-sdk/src/fdai_evaluation_sdk/contracts.py"
    _write(tmp_path, path, "def identity[T](value: T) -> T:\n    return value\n")
    assert _run(tmp_path).returncode == 0

    _write(
        tmp_path,
        path,
        "from fdai.core import control_loop\ndef identity[T](value: T) -> T:\n    return value\n",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "SDK MUST NOT import FDAI" in result.stdout
