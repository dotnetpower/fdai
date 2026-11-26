from __future__ import annotations

from datetime import UTC, datetime

from fdai.delivery import db_dr_postgres
from fdai.delivery.db_dr_postgres import (
    PostgresDbDrSettings,
    PostgresIntegrityChecker,
)
from fdai.shared.providers.db_dr import DbRestoreHandle, IntegrityMismatchKind


def _handle() -> DbRestoreHandle:
    return DbRestoreHandle(
        experiment_id="experiment-1",
        source_ref="source",
        target_ref="target",
        endpoint="restored.postgres.database.azure.com",
        resource_group="rg-drill",
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


async def test_integrity_checker_records_every_count_and_checksum_mismatch(
    monkeypatch,
) -> None:
    snapshots = iter(
        (
            {"alembic_version": (1, "source"), "stable_reference": (2, "same")},
            {"alembic_version": (2, "target"), "stable_reference": (2, "same")},
        )
    )

    async def snapshot(*_args, **_kwargs):
        return next(snapshots)

    monkeypatch.setattr(db_dr_postgres, "_table_snapshot", snapshot)
    checker = PostgresIntegrityChecker(
        settings=PostgresDbDrSettings(
            source_dsn="postgresql://user:password@source/fdai",
            tables=("alembic_version", "stable_reference"),
        )
    )

    report = await checker.check(_handle())

    assert report.is_clean is False
    assert [mismatch.kind for mismatch in report.mismatches] == [
        IntegrityMismatchKind.ROW_COUNT,
        IntegrityMismatchKind.CHECKSUM,
    ]


def test_postgres_settings_reject_duplicate_or_unsafe_table_names() -> None:
    for tables in (
        ("alembic_version", "alembic_version"),
        ("alembic_version; DROP TABLE audit_log",),
    ):
        try:
            PostgresDbDrSettings(
                source_dsn="postgresql://example.invalid/fdai",
                tables=tables,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe table set was accepted: {tables!r}")
