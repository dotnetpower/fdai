from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fdai.delivery import db_dr_drill_cli
from fdai.delivery.db_dr_drill_cli import (
    DbDrJobConfigurationError,
    DbDrJobSettings,
    execute_db_dr_drill,
)
from fdai.shared.providers.db_dr import (
    DbRestoreConfig,
    IntegrityReport,
    SmokeCheck,
    SmokeReport,
)
from fdai.shared.providers.testing.db_dr import (
    FakeDbRestoreAdapter,
    FakeIntegrityChecker,
    FakeSmokeRunner,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 31, 1, tzinfo=UTC)


def _environment() -> dict[str, str]:
    return {
        "FDAI_DR_DRILL_SOURCE_SERVER_ARM_ID": (
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg-source"
            "/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-source"
        ),
        "FDAI_DR_DRILL_TARGET_LOCATION": "koreacentral",
        "FDAI_DR_DRILL_TARGET_RESOURCE_GROUP": "rg-drill",
        "FDAI_DR_DRILL_TARGET_SERVER_PREFIX": "psql-drill",
        "FDAI_DR_DRILL_PITR_OFFSET_MINUTES": "30",
        "FDAI_DR_DRILL_INTEGRITY_TABLES": "stable_reference,alembic_version",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
    }


def test_settings_require_complete_enabled_configuration() -> None:
    for missing in (
        "FDAI_DR_DRILL_SOURCE_SERVER_ARM_ID",
        "FDAI_DR_DRILL_TARGET_LOCATION",
        "FDAI_DR_DRILL_TARGET_RESOURCE_GROUP",
        "FDAI_STATE_STORE_DSN",
    ):
        environment = _environment()
        environment.pop(missing)
        with pytest.raises(DbDrJobConfigurationError):
            DbDrJobSettings.from_environ(environment)


def test_complete_dry_run_is_not_configuration_required(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment = _environment()
    environment["FDAI_DR_DRILL_DRY_RUN"] = "1"
    monkeypatch.setattr(db_dr_drill_cli.os, "environ", environment)

    assert db_dr_drill_cli.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "dry_run",
        "execution_authority": False,
    }


async def test_successful_shadow_drill_runs_restore_verify_smoke_and_teardown() -> None:
    settings = DbDrJobSettings.from_environ(_environment())
    restore = FakeDbRestoreAdapter()
    integrity = FakeIntegrityChecker(
        report_sequence=(
            IntegrityReport(
                table_row_counts={"alembic_version": 1},
                checksums={"alembic_version": "same"},
            ),
        )
    )
    smoke = FakeSmokeRunner(
        report_sequence=(
            SmokeReport(
                checks=(
                    SmokeCheck(name="read", passed=True),
                    SmokeCheck(name="rolled-back-write", passed=True),
                )
            ),
        )
    )

    verdict = await execute_db_dr_drill(
        settings=settings,
        restore=restore,
        integrity=integrity,
        smoke=smoke,
        audit=InMemoryStateStore(),
        now=_NOW,
    )

    assert verdict.is_pass is True
    assert len(restore.restored) == 1
    assert len(restore.torn_down) == 1


def test_main_returns_sanitized_failure_without_resource_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment = _environment()
    monkeypatch.setattr(db_dr_drill_cli.os, "environ", environment)

    async def failed():
        settings = DbDrJobSettings.from_environ(environment)
        config: DbRestoreConfig = settings.restore_config(now=_NOW)
        restore = FakeDbRestoreAdapter(teardown_error=RuntimeError("provider secret detail"))
        return await execute_db_dr_drill(
            settings=settings,
            restore=restore,
            integrity=FakeIntegrityChecker(
                report_sequence=(IntegrityReport(table_row_counts={}, checksums={}),)
            ),
            smoke=FakeSmokeRunner(
                report_sequence=(
                    SmokeReport(
                        checks=(
                            SmokeCheck(name="read", passed=True),
                            SmokeCheck(name="write", passed=True),
                        )
                    ),
                )
            ),
            audit=InMemoryStateStore(),
            now=config.point_in_time_utc or _NOW,
        )

    monkeypatch.setattr(db_dr_drill_cli, "run_once", failed)

    assert db_dr_drill_cli.main([]) == 3
    rendered = capsys.readouterr().out
    assert json.loads(rendered)["status"] == "cleanup_failed"
    assert "provider secret detail" not in rendered
    assert "rg-drill" not in rendered
