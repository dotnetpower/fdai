from __future__ import annotations

import importlib
from pathlib import Path

from fdai.delivery.db_dr_drill_cli import DbDrJobSettings
from fdai.delivery.scheduler_tick_cli import SchedulerJobSettings

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra" / "modules" / "compute" / "container-apps"


def test_job_entrypoints_are_importable_and_match_terraform() -> None:
    scheduler = (_MODULE / "scheduler_job.tf").read_text(encoding="utf-8")
    db_dr = (_MODULE / "dr_drill_job.tf").read_text(encoding="utf-8")

    importlib.import_module("fdai.delivery.scheduler_tick_cli")
    importlib.import_module("fdai.delivery.db_dr_drill_cli")
    assert 'command = ["python", "-m", "fdai.delivery.scheduler_tick_cli"]' in scheduler
    assert 'command = ["python", "-m", "fdai.delivery.db_dr_drill_cli"]' in db_dr


def test_jobs_use_distinct_non_executor_identities_and_secret_references() -> None:
    scheduler = (_MODULE / "scheduler_job.tf").read_text(encoding="utf-8")
    db_dr = (_MODULE / "dr_drill_job.tf").read_text(encoding="utf-8")
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert "executor_identity" not in scheduler
    assert "var.scheduler_identity_id" in scheduler
    assert "executor_identity" not in db_dr
    assert "var.dr_drill_identity_id" in db_dr
    assert "scheduler_eventhubs_sender" in root
    assert "scheduler_kv_secrets_user" in root
    assert "dr_drill_source_reader" in root
    assert "dr_drill_target_contributor" in root
    assert '"PostgreSQL Flexible Management Service Contributor"' in root
    assert '"Contributor"' not in "\n".join(
        line for line in root.splitlines() if "dr_drill" in line
    )


def test_complete_job_environment_parses_without_configuration_required() -> None:
    scheduler = SchedulerJobSettings.from_environ(
        {
            "FDAI_SCHEDULE_STORE_DSN": "postgresql://example.invalid/fdai",
            "KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
            "KAFKA_TOPIC_EVENTS": "fdai.events",
        }
    )
    db_dr = DbDrJobSettings.from_environ(
        {
            "FDAI_DR_DRILL_SOURCE_SERVER_ARM_ID": (
                "/subscriptions/00000000-0000-0000-0000-000000000000"
                "/resourceGroups/rg-source"
                "/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-source"
            ),
            "FDAI_DR_DRILL_TARGET_LOCATION": "koreacentral",
            "FDAI_DR_DRILL_TARGET_RESOURCE_GROUP": "rg-drill",
            "FDAI_DR_DRILL_INTEGRITY_TABLES": "alembic_version",
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        }
    )

    assert scheduler.topic == "fdai.events"
    assert db_dr.integrity_tables == ("alembic_version",)
