"""Operational instance certification delivery reducer tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MethodType
from typing import Any

import pytest
from fdai.core.ontology_platform.operational_instance_certification import (
    OperationalCertificationAxis,
    OperationalCertificationStatus,
)
from fdai.delivery.operational_instance_certification import (
    OperationalCertificationSnapshot,
    build_operational_certification_snapshot,
    reduce_operational_instance_certification,
)
from fdai.delivery.operational_instance_certification_cli import (
    _write_record,
    receipt_record,
    snapshot_from_record,
    snapshot_record,
)
from fdai.delivery.operational_instance_certification_postgres import (
    PostgresOperationalCertificationSource,
    PostgresOperationalCertificationSourceConfig,
)

_START = datetime(2026, 8, 25, tzinfo=UTC)
_RELEASE = "sha256:" + "a" * 64


class _Cursor:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _Connection:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.read_only: list[bool] = []
        self.executions: list[tuple[str, object]] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def set_read_only(self, value: bool) -> None:
        self.read_only.append(value)

    async def execute(self, query: str, parameters: object = None) -> _Cursor:
        self.executions.append((query, parameters))
        return _Cursor(None if "set_config" in query else self.row)


def _source(connection: _Connection) -> PostgresOperationalCertificationSource:
    source = PostgresOperationalCertificationSource(
        config=PostgresOperationalCertificationSourceConfig(dsn="postgresql://example")
    )

    async def connect(_self: object) -> _Connection:
        return connection

    source._connect = MethodType(connect, source)  # type: ignore[method-assign]
    return source


def _database_row() -> dict[str, Any]:
    return {
        "measured_at": _START,
        "ontology_status": {"ontology_release_digest": _RELEASE},
        "database_bytes": 1000,
        "freshness_seconds": Decimal("12.5"),
        "lag_seconds": Decimal("3.5"),
        "collection_health": {"provider_pressure": {"budget_remaining_ratio": 0.75}},
        "rollup_total_count": 4,
        "rollup_complete_count": 3,
        "restore_total_count": 2,
        "restore_passed_count": 1,
        "provider_failure_recovery_seconds": Decimal("42"),
    }


def test_postgres_source_config_normalizes_service_dsn_for_psycopg() -> None:
    config = PostgresOperationalCertificationSourceConfig(
        dsn="postgresql+psycopg://example.invalid/fdai"
    )

    assert config.psycopg_dsn == "postgresql://example.invalid/fdai"


def _snapshot(
    *,
    measured_at: datetime,
    database_bytes: int | None = 1000,
    freshness_seconds: Decimal | None = Decimal("5"),
    api_pressure_ratio: Decimal | None = Decimal("0.25"),
    lag_seconds: Decimal | None = Decimal("2"),
    rollup_total_count: int = 4,
    rollup_complete_count: int = 3,
    restore_total_count: int = 2,
    restore_passed_count: int = 2,
    provider_failure_recovery_seconds: Decimal | None = Decimal("30"),
    ontology_release_digest: str = _RELEASE,
) -> OperationalCertificationSnapshot:
    return build_operational_certification_snapshot(
        measured_at=measured_at,
        ontology_release_digest=ontology_release_digest,
        database_bytes=database_bytes,
        freshness_seconds=freshness_seconds,
        api_pressure_ratio=api_pressure_ratio,
        lag_seconds=lag_seconds,
        rollup_total_count=rollup_total_count,
        rollup_complete_count=rollup_complete_count,
        restore_total_count=restore_total_count,
        restore_passed_count=restore_passed_count,
        provider_failure_recovery_seconds=provider_failure_recovery_seconds,
    )


def test_reducer_builds_complete_content_addressed_seven_axis_receipt() -> None:
    start = _snapshot(measured_at=_START, database_bytes=1000)
    end = _snapshot(measured_at=_START + timedelta(minutes=30), database_bytes=1300)

    receipt = reduce_operational_instance_certification(
        start,
        end,
        recorded_at=end.measured_at + timedelta(seconds=1),
    )

    values = {measurement.axis: measurement.value for measurement in receipt.measurements}
    assert receipt.complete is True
    assert values == {
        OperationalCertificationAxis.API_PRESSURE: Decimal("0.25"),
        OperationalCertificationAxis.ARCHIVE_RESTORE: Decimal("1"),
        OperationalCertificationAxis.FRESHNESS: Decimal("5"),
        OperationalCertificationAxis.LAG: Decimal("2"),
        OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY: Decimal("30"),
        OperationalCertificationAxis.ROLLUP_COVERAGE: Decimal("0.75"),
        OperationalCertificationAxis.STORAGE_GROWTH: Decimal("600"),
    }
    assert receipt.observation_authority is False
    assert receipt.mutation_authority is False
    assert receipt.execution_authority is False


def test_reducer_keeps_unobserved_axes_unavailable_instead_of_zero() -> None:
    start = _snapshot(measured_at=_START, database_bytes=None)
    end = _snapshot(
        measured_at=_START + timedelta(minutes=10),
        database_bytes=None,
        freshness_seconds=None,
        api_pressure_ratio=None,
        lag_seconds=None,
        rollup_total_count=0,
        rollup_complete_count=0,
        restore_total_count=0,
        restore_passed_count=0,
        provider_failure_recovery_seconds=None,
    )

    receipt = reduce_operational_instance_certification(
        start,
        end,
        recorded_at=end.measured_at,
    )

    assert receipt.complete is False
    assert len(receipt.unavailable_axes) == 7
    assert {measurement.axis: measurement.reason_codes for measurement in receipt.measurements} == {
        OperationalCertificationAxis.API_PRESSURE: ("api_pressure_measurement_unavailable",),
        OperationalCertificationAxis.ARCHIVE_RESTORE: ("archive_restore_measurement_unavailable",),
        OperationalCertificationAxis.FRESHNESS: ("freshness_measurement_unavailable",),
        OperationalCertificationAxis.LAG: ("lag_measurement_unavailable",),
        OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY: (
            "provider_failure_recovery_measurement_unavailable",
        ),
        OperationalCertificationAxis.ROLLUP_COVERAGE: ("rollup_measurement_unavailable",),
        OperationalCertificationAxis.STORAGE_GROWTH: ("storage_measurement_unavailable",),
    }
    assert all(
        measurement.status is OperationalCertificationStatus.UNAVAILABLE
        and measurement.value is None
        for measurement in receipt.measurements
    )


def test_reducer_preserves_negative_storage_growth() -> None:
    start = _snapshot(measured_at=_START, database_bytes=1300)
    end = _snapshot(measured_at=_START + timedelta(hours=1), database_bytes=1000)

    receipt = reduce_operational_instance_certification(
        start,
        end,
        recorded_at=end.measured_at,
    )

    storage = next(
        measurement
        for measurement in receipt.measurements
        if measurement.axis is OperationalCertificationAxis.STORAGE_GROWTH
    )
    assert storage.value == Decimal("-300")


def test_reducer_rejects_release_drift_and_snapshot_tampering() -> None:
    start = _snapshot(measured_at=_START)
    end = _snapshot(
        measured_at=_START + timedelta(minutes=1),
        ontology_release_digest="sha256:" + "b" * 64,
    )

    with pytest.raises(ValueError, match="same ontology release"):
        reduce_operational_instance_certification(start, end, recorded_at=end.measured_at)
    with pytest.raises(ValueError, match="digest does not match"):
        replace(start, database_bytes=1001)


async def test_postgres_source_reads_one_sanitized_read_only_snapshot() -> None:
    connection = _Connection(_database_row())

    snapshot = await _source(connection).capture()

    assert connection.read_only == [True]
    assert len(connection.executions) == 2
    query = connection.executions[1][0]
    assert "pg_database_size" in query
    assert "operational_archive_manifest" in query
    assert "operational_archive_restore_receipt" in query
    assert "resource_id" not in query
    assert snapshot.ontology_release_digest == _RELEASE
    assert snapshot.api_pressure_ratio == Decimal("0.25")
    assert snapshot.provider_failure_recovery_seconds == Decimal("42")


async def test_postgres_source_keeps_nullable_pressure_unavailable() -> None:
    row = _database_row()
    row["collection_health"] = {"provider_pressure": {"budget_remaining_ratio": None}}

    snapshot = await _source(_Connection(row)).capture()

    assert snapshot.api_pressure_ratio is None


async def test_postgres_source_maps_explicit_healthy_pressure_to_zero() -> None:
    row = _database_row()
    row["collection_health"] = {
        "provider_pressure": {
            "state": "healthy",
            "budget_remaining_ratio": None,
            "retry_after_seconds": None,
        }
    }

    snapshot = await _source(_Connection(row)).capture()

    assert snapshot.api_pressure_ratio == Decimal(0)


async def test_postgres_source_requires_exact_release_binding() -> None:
    row = _database_row()
    row["ontology_status"] = {"status": "unavailable"}

    with pytest.raises(ValueError, match="exact ontology release is unavailable"):
        await _source(_Connection(row)).capture()


def test_snapshot_record_round_trips_and_rejects_tampering() -> None:
    snapshot = _snapshot(measured_at=_START)
    record = snapshot_record(snapshot)

    assert snapshot_from_record(record) == snapshot
    record["database_bytes"] = 1001
    with pytest.raises(ValueError, match="digest mismatch"):
        snapshot_from_record(record)


def test_receipt_record_preserves_no_authority_and_unavailable_axes() -> None:
    start = _snapshot(measured_at=_START, database_bytes=None)
    end = _snapshot(
        measured_at=_START + timedelta(minutes=1),
        database_bytes=None,
        api_pressure_ratio=None,
        restore_total_count=0,
        restore_passed_count=0,
    )
    receipt = reduce_operational_instance_certification(
        start,
        end,
        recorded_at=end.measured_at,
    )

    record = receipt_record(receipt)

    assert record["complete"] is False
    assert record["observation_authority"] is False
    assert record["mutation_authority"] is False
    assert record["execution_authority"] is False
    assert record["unavailable_axes"] == ["api_pressure", "archive_restore", "storage_growth"]


def test_artifact_writer_is_atomic_private_and_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "campaign" / "snapshot.json"

    _write_record(path, snapshot_record(_snapshot(measured_at=_START)))

    assert path.stat().st_mode & 0o777 == 0o600
    assert snapshot_from_record(json.loads(path.read_text(encoding="utf-8"))).digest
