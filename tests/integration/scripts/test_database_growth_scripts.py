"""Policy tests for the local database growth report and compaction scripts."""

from __future__ import annotations

import importlib.util
import json
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


@pytest.mark.parametrize("operation", ["_usage", "_bounds"])
def test_compaction_reads_have_connection_and_statement_deadlines(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("compact_database_read_deadlines", "compact-local-database.py")
    connect = MagicMock()
    connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (
        0,
        0,
        0,
    )
    monkeypatch.setattr(module.psycopg, "connect", connect)

    arguments = ("runtime-dsn", "example:", 10) if operation == "_usage" else ("runtime-dsn",)
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
    assert connection.execute.call_args_list[0].args[0] == "VACUUM (ANALYZE) state_kv"
    assert report["vacuum_mode"] == "ordinary"
    store.aclose.assert_awaited_once()


def test_table_storage_separates_heap_index_toast_and_estimated_rows() -> None:
    record = _REPORT.table_storage(
        ("public", "example", 42, 1000, 300, 200, 8, 2, 10, 20, 3, 5, None, None)
    )
    assert record["total_bytes"] == sum(
        record[field] for field in ("heap_bytes", "index_bytes", "toast_bytes")
    )
    assert record["heap_bytes"] == 500
    assert record["estimated_live_rows"] == 8
    assert record["estimated_dead_rows"] == 2
    assert record["updates"] == 20
    assert record["hot_updates"] == 5


def test_inconsistent_physical_sizes_are_not_presented_as_negative_heap_usage() -> None:
    with pytest.raises(RuntimeError, match="sizes changed"):
        _REPORT.table_storage(
            ("public", "example", 42, 100, 300, 200, 8, 2, 10, 20, 3, 5, None, None)
        )


def test_relation_growth_rejects_recreated_relations() -> None:
    previous = {
        "at": 0.0,
        "relations": {"public.example": {"oid": 42, "total_bytes": 100}},
    }
    current = {"relation": "public.example", "oid": 42, "total_bytes": 3700}
    assert _REPORT.relation_growth(previous, current, 3600.0) == 3600.0
    assert _REPORT.relation_growth(previous, {**current, "oid": 43}, 3600.0) is None


def test_corrupt_sample_is_reported_instead_of_silently_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"database_oid": 42, "at": "invalid"}), encoding="utf-8")
    monkeypatch.setattr(_REPORT, "_SAMPLE_PATH", sample)
    assert _REPORT._previous_sample(42) is None
    assert "WARNING" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["invalid", "0", "-1"])
def test_invalid_database_bound_is_explicit(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_LOCAL_DATABASE_RECREATE_MAX_BYTES", value)
    with pytest.raises(SystemExit, match="positive integer"):
        _REPORT._bound()


async def test_compaction_byte_budget_never_discards_the_required_newest_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_byte_budget", "compact-local-database.py")
    store = MagicMock()
    monkeypatch.setattr(module, "PostgresStateStore", store)
    monkeypatch.setattr(module, "_dsn", lambda: "local")
    monkeypatch.setattr(module, "_bounds", lambda dsn: {"example:": 2})
    monkeypatch.setattr(
        module,
        "_usage",
        lambda dsn, prefix, keep: {
            "rows": 3,
            "value_storage_bytes": 300,
            "retained_value_storage_bytes": 200,
        },
    )
    report = await module._run(apply=True, vacuum=False, max_prefix_bytes=100)
    assert report["status"] == "blocked"
    assert report["prefixes"]["example:"]["blocked"] == "retained_window_exceeds_byte_budget"
    store.assert_not_called()


async def test_compaction_dry_run_measures_bytes_without_constructing_a_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_dry_run", "compact-local-database.py")
    store = MagicMock()
    monkeypatch.setattr(module, "PostgresStateStore", store)
    monkeypatch.setattr(module, "_dsn", lambda: "local")
    monkeypatch.setattr(module, "_bounds", lambda dsn: {"example:": 2})
    monkeypatch.setattr(
        module,
        "_usage",
        lambda dsn, prefix, keep: {
            "rows": 3,
            "value_storage_bytes": 300,
            "retained_value_storage_bytes": 200,
        },
    )
    report = await module._run(apply=False, vacuum=False, max_prefix_bytes=250)
    assert report["status"] == "ready"
    assert report["prefixes"]["example:"]["would_delete"] == 1
    store.assert_not_called()


def test_growth_report_sets_connection_statement_and_lock_deadlines() -> None:
    assert "statement_timeout=10000" in _REPORT._CONNECTION_OPTIONS
    assert "lock_timeout=1000" in _REPORT._CONNECTION_OPTIONS
    assert "pg_toast" in _REPORT._TABLE_STORAGE_SQL
    assert "pg_stat_user_tables" in _REPORT._TABLE_STORAGE_SQL
    assert "n.nspname='public'" not in _REPORT._TABLE_STORAGE_SQL


def test_json_report_contains_storage_breakdown_and_index_usage_without_sampling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    connection = MagicMock()

    def execute(query: str, parameters: tuple[object, ...] = ()) -> MagicMock:
        cursor = MagicMock()
        if query == _REPORT._TABLE_STORAGE_SQL:
            cursor.fetchall.return_value = [
                ("public", "example", 42, 1000, 300, 200, 8, 2, 10, 20, 3, 5, None, None)
            ]
        elif query == _REPORT._INDEX_STORAGE_SQL:
            assert parameters == (5,)
            cursor.fetchall.return_value = [
                ("public", "example", "example_pkey", 300, 7, True, True)
            ]
        elif "pg_database_size" in query:
            cursor.fetchone.return_value = (1000,)
        elif "SELECT oid" in query:
            cursor.fetchone.return_value = (42,)
        elif "stats_reset" in query:
            cursor.fetchone.return_value = (None,)
        else:
            assert query in {
                "SET default_transaction_read_only = on",
                "SET TRANSACTION READ ONLY",
            }
        return cursor

    connection.execute.side_effect = execute
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    sample = tmp_path / "sample.json"
    monkeypatch.setattr(_REPORT.psycopg, "connect", connect)
    monkeypatch.setattr(_REPORT, "_dsn", lambda: "local")
    monkeypatch.setattr(_REPORT, "_SAMPLE_PATH", sample)
    monkeypatch.setattr(sys, "argv", ["report-database-growth.py", "--json", "--no-sample"])
    assert _REPORT.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tables"][0]["heap_bytes"] == 500
    assert report["tables"][0]["toast_bytes"] == 200
    assert report["indexes"][0]["scans_since_stats_reset"] == 7
    assert report["indexes"][0]["primary"] is True
    assert not sample.exists()
    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert connect.call_args.kwargs["options"] == _REPORT._CONNECTION_OPTIONS


def test_detailed_report_distinguishes_unavailable_permissions_from_missing_tables() -> None:
    connection = MagicMock()

    def execute(query: str, parameters: tuple[object, ...] = ()) -> MagicMock:
        cursor = MagicMock()
        if query == "SELECT to_regclass(%s)":
            cursor.fetchone.return_value = (
                "trusted_artifact" if parameters == ("trusted_artifact",) else None,
            )
        else:
            if "FROM pg_stat_database" in query:
                cursor.fetchone.return_value = (None, 5, 6, 7, 0.0, 0.0)
            else:
                assert "has_table_privilege" in query
                cursor.fetchone.return_value = (False,)
        return cursor

    connection.execute.side_effect = execute
    details = _REPORT.storage_details(connection)
    assert details["trusted_artifact"] == {"status": "select_permission_required"}
    assert details["conversation_image"] == {"status": "not_installed"}
    assert details["retention_policies"] == {"status": "not_installed"}
    assert details["state_families"] == {"status": "not_installed"}
    assert details["database_activity"]["updated_rows"] == 6


def test_state_family_diagnostics_use_fixed_names_and_never_return_keys_or_values() -> None:
    query = _REPORT._STATE_FAMILY_SQL
    assert "pg_column_size(value)" in query
    assert "GROUP BY family" in query
    assert "SELECT key," not in query
    assert "SELECT value," not in query
    for family in (
        "baseline_outcomes",
        "heimdall_episodes",
        "heimdall_readiness",
        "control_loop_measurements",
        "inventory_state",
        "operator_projections",
        "other",
    ):
        assert "'" + family + "'" in query


def test_detailed_report_exposes_state_storage_and_write_totals_without_payloads() -> None:
    connection = MagicMock()

    def execute(query: str, parameters: tuple[object, ...] = ()) -> MagicMock:
        cursor = MagicMock()
        if query == "SELECT to_regclass(%s)":
            cursor.fetchone.return_value = ("state_kv" if parameters == ("state_kv",) else None,)
        elif "has_table_privilege" in query:
            cursor.fetchone.return_value = (True,)
        elif query == _REPORT._STATE_FAMILY_SQL:
            cursor.fetchall.return_value = [
                ("heimdall_episodes", 4, 1024, 512),
                ("other", 2, 128, 64),
            ]
        else:
            assert "FROM pg_stat_database" in query
            cursor.fetchone.return_value = (None, 9, 12, 3, 0.0, 0.0)
        return cursor

    connection.execute.side_effect = execute
    details = _REPORT.storage_details(connection)
    assert details["state_families"][0] == {
        "family": "heimdall_episodes",
        "rows": 4,
        "value_storage_bytes": 1024,
        "largest_value_bytes": 512,
    }
    assert details["database_activity"]["updated_rows"] == 12
    assert details["database_activity"]["timing_requires_track_io_timing"] is True
    assert "payload" not in json.dumps(details)


async def test_compaction_rechecks_concurrent_growth_against_the_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_concurrent_budget", "compact-local-database.py")
    store = MagicMock()
    store.delete_states_beyond = AsyncMock(return_value=1)
    store.aclose = AsyncMock()
    monkeypatch.setattr(module, "PostgresStateStore", lambda **kwargs: store)
    monkeypatch.setattr(module, "_dsn", lambda: "local")
    monkeypatch.setattr(module, "_bounds", lambda dsn: {"example:": 2})
    usage = MagicMock(
        side_effect=[
            {"rows": 3, "value_storage_bytes": 300, "retained_value_storage_bytes": 200},
            {"rows": 3, "value_storage_bytes": 400, "retained_value_storage_bytes": 300},
        ]
    )
    monkeypatch.setattr(module, "_usage", usage)
    report = await module._run(apply=True, vacuum=False, max_prefix_bytes=250)
    assert report["status"] == "blocked"
    assert report["prefixes"]["example:"]["deleted"] == 1
    assert (
        report["prefixes"]["example:"]["blocked"] == "byte_budget_exceeded_after_concurrent_writes"
    )
    store.aclose.assert_awaited_once()


async def test_compaction_reports_a_remaining_row_backlog_without_a_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_concurrent_rows", "compact-local-database.py")
    store = MagicMock()
    store.delete_states_beyond = AsyncMock(return_value=1)
    store.aclose = AsyncMock()
    monkeypatch.setattr(module, "PostgresStateStore", lambda **kwargs: store)
    monkeypatch.setattr(module, "_dsn", lambda: "local")
    monkeypatch.setattr(module, "_bounds", lambda dsn: {"example:": 2})
    monkeypatch.setattr(
        module,
        "_usage",
        lambda dsn, prefix, keep: {
            "rows": 3,
            "value_storage_bytes": 300,
            "retained_value_storage_bytes": 200,
        },
    )
    report = await module._run(apply=True, vacuum=False)
    assert report["status"] == "blocked"
    assert report["prefixes"]["example:"]["remaining_rows"] == 3
    assert report["prefixes"]["example:"]["blocked"] == "retention_backlog_after_concurrent_writes"
