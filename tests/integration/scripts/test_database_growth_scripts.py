"""Policy tests for the local database growth report and compaction scripts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_LOCAL = _ROOT / "scripts/deployment/local"


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _LOCAL / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_REPORT = _load("report_database_growth", "report-database-growth.py")
_GIB = 1024**3


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "ok"), (int(1.4 * _GIB), "ok"), (int(1.6 * _GIB), "warn"), (2 * _GIB, "over")],
)
def test_assess_warns_before_the_recreation_guard(size: int, expected: str) -> None:
    assert _REPORT.assess(size, 2 * _GIB) == expected


def test_growth_needs_a_usable_previous_sample() -> None:
    assert _REPORT.growth_per_hour(None, 10, 100.0) is None
    assert _REPORT.growth_per_hour({"at": 90.0, "size_bytes": 1}, 10, 100.0) is None
    assert _REPORT.growth_per_hour({"at": 0.0, "size_bytes": 0}, 3600, 3600.0) == 3600.0


@pytest.mark.parametrize("script", ["report-database-growth.py", "compact-local-database.py"])
@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u@example.invalid:5432/fdai",
        "postgresql://u@127.0.0.1:5433/fdai",
        "postgresql://u@127.0.0.1:5432/other",
    ],
)
def test_scripts_accept_only_the_loopback_development_database(
    script: str, dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path[:0] = [
        str(_ROOT / "services/core-control-plane/src"),
        str(_ROOT / "packages/service-contracts/src"),
    ]
    module = _load("db_script_" + script.removesuffix(".py").replace("-", "_"), script)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", dsn)

    with pytest.raises(SystemExit, match="loopback port 5432 and database fdai"):
        module._dsn()


def test_dev_status_reports_database_growth() -> None:
    assert "report-database-growth.py" in (_LOCAL / "dev-status.sh").read_text(encoding="utf-8")
