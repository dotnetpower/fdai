"""Policy tests for the local database growth report and compaction scripts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.parametrize("operation", ["_count", "_bounds"])
def test_compaction_reads_have_connection_and_statement_deadlines(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("compact_database_read_deadlines", "compact-local-database.py")
    connect = MagicMock()
    connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (0,)
    monkeypatch.setattr(module.psycopg, "connect", connect)

    arguments = ("runtime-dsn", "example:") if operation == "_count" else ("runtime-dsn",)
    getattr(module, operation)(*arguments)

    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert "statement_timeout=30000" in connect.call_args.kwargs["options"]
    assert "lock_timeout=1000" in connect.call_args.kwargs["options"]


async def test_compaction_vacuum_has_connection_and_lock_deadlines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_vacuum_deadlines", "compact-local-database.py")
    connect = MagicMock()
    store = MagicMock()
    store.aclose = AsyncMock()
    monkeypatch.setattr(module.psycopg, "connect", connect)
    monkeypatch.setattr(module, "PostgresStateStore", lambda **kwargs: store)
    monkeypatch.setattr(module, "_dsn", lambda variable="FDAI_STATE_STORE_DSN": variable)
    monkeypatch.setattr(module, "_bounds", lambda dsn: {})

    report = await module._run(apply=True, vacuum=True)

    assert report["vacuumed"] == "state_kv"
    assert connect.call_args.args == ("FDAI_DATABASE_URL",)
    assert connect.call_args.kwargs["autocommit"] is True
    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert "statement_timeout=30000" in connect.call_args.kwargs["options"]
    assert "lock_timeout=1000" in connect.call_args.kwargs["options"]
    connection = connect.return_value.__enter__.return_value
    assert connection.execute.call_args_list[0].args[0] == (
        "ALTER TABLE state_kv SET (autovacuum_vacuum_scale_factor=0.01, "
        "autovacuum_vacuum_threshold=1000, toast.autovacuum_vacuum_scale_factor=0.01, "
        "toast.autovacuum_vacuum_threshold=1000)"
    )
    store.aclose.assert_awaited_once()
