"""Delivery-owned executable composition for one Azure PostgreSQL DB-DR drill."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import psycopg

from fdai.core.verticals.resilience.db_dr_verifier import (
    DbDrOutcome,
    DbDrVerdict,
    DbDrVerifier,
)
from fdai.delivery.azure.db_dr_restore import AzurePostgresRestoreAdapter
from fdai.delivery.azure.workload_identity import (
    ManagedIdentityConfigurationError,
    ManagedIdentityWorkloadIdentity,
)
from fdai.delivery.db_dr_postgres import (
    PostgresDbDrSettings,
    PostgresIntegrityChecker,
    PostgresSmokeRunner,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.providers.db_dr import (
    DbRestoreAdapter,
    DbRestoreConfig,
    IntegrityChecker,
    SmokeRunner,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.delivery.db_dr_drill_cli")


class DbDrJobConfigurationError(ValueError):
    """Required DB-DR Job configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class DbDrJobSettings:
    """Validated, secret-preserving bindings for one scheduled DB-DR run."""

    source_server_arm_id: str
    target_location: str
    target_resource_group: str
    target_server_prefix: str
    state_store_dsn: str
    integrity_tables: tuple[str, ...]
    pitr_offset_minutes: int = 30

    def __post_init__(self) -> None:
        for name, value in (
            ("source_server_arm_id", self.source_server_arm_id),
            ("target_location", self.target_location),
            ("target_resource_group", self.target_resource_group),
            ("target_server_prefix", self.target_server_prefix),
            ("state_store_dsn", self.state_store_dsn),
        ):
            if not value.strip():
                raise DbDrJobConfigurationError(f"DbDrJobSettings.{name} MUST be non-empty")
        if len(self.target_server_prefix) > 54:
            raise DbDrJobConfigurationError(
                "DbDrJobSettings.target_server_prefix MUST contain at most 54 characters"
            )
        if not 1 <= self.pitr_offset_minutes <= 10_080:
            raise DbDrJobConfigurationError(
                "DbDrJobSettings.pitr_offset_minutes MUST be between 1 and 10080"
            )
        try:
            PostgresDbDrSettings(
                source_dsn=self.state_store_dsn,
                tables=self.integrity_tables,
            )
        except ValueError as exc:
            raise DbDrJobConfigurationError(str(exc)) from exc

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str],
        *,
        require_dsn: bool = True,
    ) -> DbDrJobSettings:
        tables = tuple(
            sorted(
                {
                    item.strip()
                    for item in environ.get("FDAI_DR_DRILL_INTEGRITY_TABLES", "").split(",")
                    if item.strip()
                }
            )
        )
        state_store_dsn = environ.get("FDAI_STATE_STORE_DSN", "").strip()
        if not require_dsn and not state_store_dsn:
            state_store_dsn = "postgresql://dry-run.invalid/fdai"
        return cls(
            source_server_arm_id=_required(environ, "FDAI_DR_DRILL_SOURCE_SERVER_ARM_ID"),
            target_location=_required(environ, "FDAI_DR_DRILL_TARGET_LOCATION"),
            target_resource_group=_required(environ, "FDAI_DR_DRILL_TARGET_RESOURCE_GROUP"),
            target_server_prefix=(
                environ.get("FDAI_DR_DRILL_TARGET_SERVER_PREFIX", "").strip() or "psql-drill"
            ),
            state_store_dsn=state_store_dsn,
            integrity_tables=tables,
            pitr_offset_minutes=_bounded_integer(
                environ.get("FDAI_DR_DRILL_PITR_OFFSET_MINUTES", ""),
                default=30,
                minimum=1,
                maximum=10_080,
            ),
        )

    def restore_config(self, *, now: datetime) -> DbRestoreConfig:
        if now.tzinfo is None:
            raise ValueError("DB-DR clock MUST be timezone-aware")
        slug = now.astimezone(UTC).strftime("%m%d%H%M")
        return DbRestoreConfig(
            experiment_id=f"db-dr-drill-{now.astimezone(UTC).strftime('%Y%m%d-%H%M')}",
            source_ref=self.source_server_arm_id,
            target_server_name=f"{self.target_server_prefix}-{slug}",
            target_resource_group=self.target_resource_group,
            target_location=self.target_location,
            point_in_time_utc=now - timedelta(minutes=self.pitr_offset_minutes),
        )


async def execute_db_dr_drill(
    *,
    settings: DbDrJobSettings,
    restore: DbRestoreAdapter,
    integrity: IntegrityChecker,
    smoke: SmokeRunner,
    audit: StateStore,
    now: datetime | None = None,
) -> DbDrVerdict:
    """Run the provider-neutral verifier with delivery-owned adapters."""

    return await DbDrVerifier(
        restore=restore,
        integrity=integrity,
        smoke=smoke,
        audit=audit,
    ).run(settings.restore_config(now=now or datetime.now(UTC)))


async def run_once(
    environ: Mapping[str, str] | None = None,
) -> DbDrVerdict:
    """Compose Azure restore and PostgreSQL verification adapters."""

    environment = os.environ if environ is None else environ
    settings = DbDrJobSettings.from_environ(environment)
    postgres_settings = PostgresDbDrSettings(
        source_dsn=settings.state_store_dsn,
        tables=settings.integrity_tables,
    )
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
    ) as http_client:
        identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=http_client,
            env=environment,
        )
        return await execute_db_dr_drill(
            settings=settings,
            restore=AzurePostgresRestoreAdapter(
                identity=identity,
                http_client=http_client,
            ),
            integrity=PostgresIntegrityChecker(settings=postgres_settings),
            smoke=PostgresSmokeRunner(settings=postgres_settings),
            audit=PostgresStateStore(config=PostgresStateStoreConfig(dsn=settings.state_store_dsn)),
        )


def report_summary(verdict: DbDrVerdict) -> dict[str, object]:
    """Return a bounded terminal summary without resource ids or provider text."""

    return {
        "status": verdict.outcome.value,
        "passed": verdict.is_pass,
        "cleanup_succeeded": verdict.cleanup_succeeded,
        "execution_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Run one DB-DR drill with stable sanitized process outcomes."""

    arguments = argv if argv is not None else sys.argv[1:]
    if arguments:
        print(json.dumps({"status": "invalid_arguments"}, sort_keys=True))
        return 2
    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    dry_run = os.environ.get("FDAI_DR_DRILL_DRY_RUN", "").strip().casefold() in {
        "1",
        "true",
        "yes",
    }
    try:
        if dry_run:
            settings = DbDrJobSettings.from_environ(os.environ, require_dsn=False)
            settings.restore_config(now=datetime.now(UTC))
            print(
                json.dumps(
                    {"status": "dry_run", "execution_authority": False},
                    sort_keys=True,
                )
            )
            return 0
        verdict = asyncio.run(run_once())
    except DbDrJobConfigurationError as exc:
        _LOGGER.error("db_dr_drill_configuration_invalid", extra={"error_kind": type(exc).__name__})
        print(json.dumps({"status": "configuration_required"}, sort_keys=True))
        return 2
    except (
        ManagedIdentityConfigurationError,
        httpx.HTTPError,
        psycopg.Error,
        OSError,
        TimeoutError,
    ) as exc:
        _LOGGER.error("db_dr_drill_retry_required", extra={"error_kind": type(exc).__name__})
        print(
            json.dumps(
                {"status": "retry_required", "error_kind": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1
    summary = report_summary(verdict)
    print(json.dumps(summary, sort_keys=True))
    return 0 if verdict.outcome is DbDrOutcome.PASSED and verdict.is_pass else 3


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise DbDrJobConfigurationError(f"{name} is required")
    return value


def _bounded_integer(raw: str, *, default: int, minimum: int, maximum: int) -> int:
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DbDrJobConfigurationError("DB-DR integer setting is invalid") from exc
    if not minimum <= value <= maximum:
        raise DbDrJobConfigurationError("DB-DR integer setting is outside its bounds")
    return value


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DbDrJobConfigurationError",
    "DbDrJobSettings",
    "execute_db_dr_drill",
    "main",
    "report_summary",
    "run_once",
]
