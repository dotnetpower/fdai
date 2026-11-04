"""Policy tests for the local database growth report and compaction scripts."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
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


def test_assess_lifecycle_depends_on_lifecycle_warnings_not_byte_size() -> None:
    assert _REPORT.assess_lifecycle([]) == "ok"
    assert _REPORT.assess_lifecycle(["public.audit_log has 60,000 live rows"]) == "warn"


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
    monkeypatch.setattr(module, "_heimdall_checkpoint", AsyncMock(return_value={"status": "ready"}))

    report = await module._run(apply=True, vacuum=True)

    assert report["vacuumed"] == "state_kv"
    assert connect.call_args.args == ("FDAI_DATABASE_URL",)
    assert connect.call_args.kwargs["autocommit"] is True
    assert connect.call_args.kwargs["connect_timeout"] == 5
    assert "statement_timeout=120000" in connect.call_args.kwargs["options"]
    assert "lock_timeout=15000" in connect.call_args.kwargs["options"]
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


async def test_compaction_byte_budget_never_discards_the_required_newest_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_byte_budget", "compact-local-database.py")
    store = MagicMock()
    monkeypatch.setattr(module, "PostgresStateStore", store)
    monkeypatch.setattr(module, "_dsn", lambda: "local")
    monkeypatch.setattr(module, "_bounds", lambda dsn: {"example:": 2})
    monkeypatch.setattr(module, "_heimdall_checkpoint", AsyncMock(return_value={}))
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
    monkeypatch.setattr(module, "_heimdall_checkpoint", AsyncMock(return_value={}))
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
        "heimdall_buckets",
        "heimdall_episodes",
        "heimdall_readiness",
        "saga_audit_checkpoint",
        "saga_verdict_aggregate",
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
    monkeypatch.setattr(module, "_heimdall_checkpoint", AsyncMock(return_value={}))
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
    monkeypatch.setattr(module, "_heimdall_checkpoint", AsyncMock(return_value={}))
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


async def test_unverifiable_heimdall_checkpoint_is_never_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_checkpoint_unverifiable", "compact-local-database.py")
    connection = MagicMock()
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(module.psycopg, "connect", connect)
    monkeypatch.setattr(module, "reachable_from_store", AsyncMock(return_value=None))

    report = await module._heimdall_checkpoint("runtime-dsn", apply=True)

    assert report["status"] == "unverifiable"
    assert not [call for call in connection.execute.call_args_list if "DELETE" in str(call.args[0])]


async def test_heimdall_checkpoint_cleanup_keeps_reachable_rows_and_batches_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("compact_database_checkpoint_cleanup", "compact-local-database.py")
    reachable = frozenset({"pantheon/heimdall/sensing-state/versions/keep"})
    monkeypatch.setattr(module, "reachable_from_store", AsyncMock(return_value=reachable))
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (3, 30)
    connection.execute.return_value.rowcount = 0
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(module.psycopg, "connect", connect)

    dry_run = await module._heimdall_checkpoint("runtime-dsn", apply=False)
    applied = await module._heimdall_checkpoint("runtime-dsn", apply=True)

    versions = "pantheon/heimdall/sensing-state/versions/"
    assert dry_run["reachable_rows"] == 1
    assert dry_run["prefixes"][versions] == {
        "reclaimable_rows": 3,
        "reclaimable_value_storage_bytes": 30,
    }
    assert applied["prefixes"][versions]["deleted"] == 0
    deletes = [call for call in connection.execute.call_args_list if "DELETE" in str(call.args[0])]
    assert deletes
    assert all(
        call.args[1][2] == sorted(reachable) and call.args[1][3] == 2_000 for call in deletes
    )


def _chain(count: int, *, anchor: str | None = None) -> list[dict[str, object]]:
    from fdai.shared.providers.audit_hash import GENESIS_HASH, next_hash

    previous, records = anchor or GENESIS_HASH, []
    for seq in range(1, count + 1):
        entry = {"action_kind": "example", "n": seq}
        digest = next_hash(previous, entry)
        records.append(
            {
                "seq": seq,
                "entry": entry,
                "previous_hash": previous,
                "entry_hash": digest,
                "created_at": "2026-11-03T00:00:00+00:00",
            }
        )
        previous = digest
    return records


def _archive_module() -> ModuleType:
    sys.path[:0] = [
        str(_ROOT / "services/core-control-plane/src"),
        str(_ROOT / "packages/service-contracts/src"),
    ]
    return _load("archive_audit_segments", "archive-audit-segments.py")


def test_audit_segment_round_trips_and_is_anchored(tmp_path: Path) -> None:
    module = _archive_module()
    records = _chain(50)

    entry = module.write_segment(tmp_path, records, anchor="0" * 64)

    assert entry["rows"] == 50 and entry["last_entry_hash"] == records[-1]["entry_hash"]
    restored = module._decode(
        module.decompress_bytes(
            (tmp_path / entry["segment"]).read_bytes(),
            max_output_size=10_000_000,
            expected_uncompressed_sha256=entry["uncompressed_sha256"],
        )
    )
    assert module.verify_records(restored, anchor="0" * 64) == entry["last_entry_hash"]
    assert not list(tmp_path.glob("*.partial"))


def test_tampered_or_unanchored_audit_rows_are_never_written(tmp_path: Path) -> None:
    module = _archive_module()
    tampered = _chain(5)
    tampered[2]["entry"] = {"action_kind": "example", "n": 999}

    with pytest.raises(ValueError, match="hash mismatch"):
        module.write_segment(tmp_path, tampered, anchor="0" * 64)
    with pytest.raises(ValueError, match="link broken"):
        module.write_segment(tmp_path, _chain(5), anchor="f" * 64)
    assert list(tmp_path.iterdir()) == []


def test_manifest_must_be_one_contiguous_chain(tmp_path: Path) -> None:
    module = _archive_module()
    first = module.write_segment(tmp_path, _chain(3), anchor="0" * 64)
    (tmp_path / "manifest.jsonl").write_text(
        json.dumps(first) + "\n" + json.dumps({**first, "first_previous_hash": "e" * 64}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="contiguous"):
        module.read_manifest(tmp_path)


def test_compaction_windows_include_resolved_hil_park_only() -> None:
    module = _load("compact_database_windows", "compact-local-database.py")

    assert module._LOCAL_WINDOWS["hil_park:"] == (500, ("status", "resolved"))
    assert not any(prefix.startswith("analyzer-publication") for prefix in module._LOCAL_WINDOWS)


def _written_archive(tmp_path: Path) -> tuple[ModuleType, dict[str, object]]:
    module = _archive_module()
    records = _chain(10)
    entry = module.write_segment(tmp_path, records, anchor="0" * 64)
    (tmp_path / "manifest.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return module, entry


def test_verify_accepts_an_intact_archive(tmp_path: Path) -> None:
    module, entry = _written_archive(tmp_path)

    report = module.verify_archive(tmp_path)

    assert report == {
        "generations": 1,
        "segments": 1,
        "rows": 10,
        "chains": [entry["last_entry_hash"]],
    }


def test_verify_of_an_empty_archive_is_vacuously_valid(tmp_path: Path) -> None:
    assert _archive_module().verify_archive(tmp_path)["segments"] == 0


@pytest.mark.parametrize("defect", ["missing", "bytes", "manifest_rows", "manifest_head"])
def test_verify_rejects_every_kind_of_archive_damage(tmp_path: Path, defect: str) -> None:
    module, entry = _written_archive(tmp_path)
    segment = tmp_path / str(entry["segment"])
    manifest = tmp_path / "manifest.jsonl"
    if defect == "missing":
        segment.unlink()
    elif defect == "bytes":
        data = bytearray(segment.read_bytes())
        data[len(data) // 2] ^= 0xFF
        segment.write_bytes(bytes(data))
    else:
        field = "rows" if defect == "manifest_rows" else "last_entry_hash"
        changed = {**entry, field: 11 if field == "rows" else "e" * 64}
        manifest.write_text(json.dumps(changed) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        module.verify_archive(tmp_path)


def test_verify_command_exits_nonzero_on_damage_without_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, entry = _written_archive(tmp_path)
    (tmp_path / str(entry["segment"])).unlink()
    monkeypatch.setattr(sys, "argv", ["archive", "--verify", "--out", str(tmp_path)])

    assert module.main() == 1
    assert "verification failed" in capsys.readouterr().err


def test_final_archive_fails_unless_it_reaches_the_table_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _archive_module()
    records = _chain(5)
    rows = [
        (
            record["seq"],
            "00000000-0000-0000-0000-000000000001",
            None,
            "actor",
            "example",
            "shadow",
            record["entry"],
            record["previous_hash"],
            record["entry_hash"],
            datetime(2026, 11, 4, tzinfo=UTC),
        )
        for record in records
    ]

    class Database:
        def __init__(self, head: int) -> None:
            self.head = head

        def __enter__(self) -> Database:
            return self

        def __exit__(self, *_arguments: object) -> bool:
            return False

        def execute(self, query: str, parameters: tuple = ()) -> object:
            handlers = {
                "to_regclass": lambda: ("audit_log",),
                "max(seq)": lambda: (self.head,),
                "ORDER BY seq LIMIT 1": lambda: (
                    records[0]["entry_hash"],
                    datetime(2026, 11, 4, tzinfo=UTC),
                ),
            }
            key = next((name for name in handlers if name in query), None)
            if key is not None:
                return SimpleNamespace(fetchone=handlers[key])
            if not parameters:
                return SimpleNamespace()
            wanted = [row for row in rows if parameters[0] < row[0] <= parameters[1]]
            return SimpleNamespace(fetchall=lambda: wanted, fetchone=lambda: None)

    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_k: Database(5))
    complete = module.archive(
        "dsn", tmp_path, older_than=timedelta(0), segment_rows=100, max_segments=5, final=True
    )
    assert complete["archived_through_seq"] == 5 and complete["rows"] == 5

    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_k: Database(9))
    with pytest.raises(SystemExit, match="stops at seq 5 but the table reaches 9"):
        module.archive(
            "dsn", tmp_path, older_than=timedelta(0), segment_rows=100, max_segments=5, final=True
        )


def test_missing_audit_table_is_reported_not_treated_as_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _archive_module()

    class Database:
        def __enter__(self) -> Database:
            return self

        def __exit__(self, *_arguments: object) -> bool:
            return False

        def execute(self, query: str, parameters: tuple = ()) -> object:
            return SimpleNamespace(fetchone=lambda: (None,))

    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_k: Database())

    report = module.archive(
        "dsn", tmp_path, older_than=timedelta(0), segment_rows=10, max_segments=1, final=True
    )

    assert report["audit_log"] == "absent" and report["rows"] == 0


def test_a_recreated_database_gets_its_own_generation_and_old_ones_stay_verifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _archive_module()
    old_entry = module.write_segment(tmp_path, _chain(4), anchor="0" * 64)
    (tmp_path / "manifest.jsonl").write_text(json.dumps(old_entry) + "\n", encoding="utf-8")

    new_records = _chain(3, anchor="0" * 64)
    new_records = [
        {**record, "entry": {"action_kind": "recreated", "n": record["seq"]}}
        for record in new_records[:1]
    ]
    from fdai.shared.providers.audit_hash import next_hash

    new_records[0]["previous_hash"] = "0" * 64
    new_records[0]["entry_hash"] = next_hash("0" * 64, new_records[0]["entry"])
    row = (
        1,
        "00000000-0000-0000-0000-000000000001",
        None,
        "actor",
        "example",
        "shadow",
        new_records[0]["entry"],
        "0" * 64,
        new_records[0]["entry_hash"],
        datetime(2026, 11, 4, tzinfo=UTC),
    )

    class Database:
        def __enter__(self) -> Database:
            return self

        def __exit__(self, *_arguments: object) -> bool:
            return False

        def execute(self, query: str, parameters: tuple = ()) -> object:
            if "to_regclass" in query:
                return SimpleNamespace(fetchone=lambda: ("audit_log",))
            if "ORDER BY seq LIMIT 1" in query:
                return SimpleNamespace(fetchone=lambda: (row[8], row[9]))
            if "max(seq)" in query:
                return SimpleNamespace(fetchone=lambda: (1,))
            if not parameters:
                return SimpleNamespace()
            return SimpleNamespace(fetchall=lambda: [row] if parameters[0] < 1 else [])

    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_k: Database())

    report = module.archive(
        "dsn", tmp_path, older_than=timedelta(0), segment_rows=10, max_segments=5, final=True
    )

    assert report["generation"] == module.generation_id(
        new_records[0]["entry_hash"], datetime(2026, 11, 4, tzinfo=UTC).isoformat()
    )
    assert report["archived_through_seq"] == 1
    assert not (tmp_path / "manifest.jsonl").exists()
    verified = module.verify_archive(tmp_path)
    assert verified["generations"] == 2 and verified["rows"] == 5


_MIB = 1024 * 1024


def test_lifecycle_warnings_report_dead_rows_cold_audit_and_expired_state_not_byte_size() -> None:
    healthy_large_tables = [
        {
            "relation": "public.state_kv",
            "total_bytes": 10 * _GIB,
            "estimated_live_rows": 5_000,
            "estimated_dead_rows": 100,
        },
        {
            "relation": "public.audit_log",
            "total_bytes": 4 * _GIB,
            "estimated_live_rows": 1_000,
            "estimated_dead_rows": 0,
        },
    ]
    assert _REPORT.lifecycle_warnings(healthy_large_tables, None) == []

    bloated_tables = [
        {
            "relation": "public.state_kv",
            "total_bytes": 50 * _MIB,
            "estimated_live_rows": 1_000,
            "estimated_dead_rows": 15_000,
        },
        {
            "relation": "public.audit_log",
            "total_bytes": 50 * _MIB,
            "estimated_live_rows": 60_000,
            "estimated_dead_rows": 0,
        },
    ]
    details = {
        "t2_cache": {"rows": 10, "expired_rows": 3},
        "state_families": [{"family": "heimdall_versions", "rows": 6_000}],
    }
    warnings = _REPORT.lifecycle_warnings(bloated_tables, details)
    assert any("dead rows" in item for item in warnings)
    assert any("archive-audit-segments.py --prune" in item for item in warnings)
    assert any("t2_cache has 3 expired rows" in item for item in warnings)
    assert any("heimdall_versions has 6,000 rows" in item for item in warnings)


def test_prune_archived_segments_writes_anchor_and_deletes_cold_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai.delivery.persistence.postgres_audit_history import parse_audit_archive_anchor

    module = _archive_module()
    records = _chain(600)
    gen_dir = tmp_path / module.generation_id(
        str(records[0]["entry_hash"]), str(records[0]["created_at"])
    )
    gen_dir.mkdir(parents=True)
    first_seg = module.write_segment(gen_dir, records[:50], anchor="0" * 64)
    (gen_dir / "manifest.jsonl").write_text(json.dumps(first_seg) + "\n", encoding="utf-8")

    anchored: list[dict[str, object]] = []
    deleted_upto: list[int] = []

    class Database:
        def __enter__(self) -> Database:
            return self

        def __exit__(self, *_arguments: object) -> bool:
            return False

        def commit(self) -> None:
            return None

        def execute(self, query: str, parameters: tuple = ()) -> object:
            if "pg_advisory_xact_lock" in query:
                return SimpleNamespace()
            if "ORDER BY seq DESC OFFSET" in query and "actor = 'Saga'" not in query:
                return SimpleNamespace(fetchone=lambda: (88,))
            if "SELECT value FROM state_kv" in query:
                return SimpleNamespace(fetchone=lambda: ({"schema_version": "3.0.0"},))
            if "actor = 'Saga'" in query:
                return SimpleNamespace(fetchone=lambda: (75,))
            if "incident." in query:
                return SimpleNamespace(fetchone=lambda: (None,))
            if "WHERE seq > %s ORDER BY seq ASC LIMIT 1" in query:
                assert parameters == (50,)
                return SimpleNamespace(fetchone=lambda: (51, records[50]["previous_hash"]))
            if "INSERT INTO state_kv" in query:
                anchored.append(json.loads(parameters[1]))
                return SimpleNamespace()
            if "DELETE FROM audit_log" in query:
                deleted_upto.append(int(parameters[0]))
                return SimpleNamespace(rowcount=50)
            raise AssertionError(f"unexpected query: {query}")

    monkeypatch.setattr(module.psycopg, "connect", lambda *_a, **_k: Database())
    deleted, through_seq = module.prune_archived_segments("dsn", gen_dir)

    assert deleted == 50 and through_seq == 50
    assert deleted_upto == [50]
    assert len(anchored) == 1
    assert parse_audit_archive_anchor(anchored[0]) == (50, str(records[49]["entry_hash"]))
