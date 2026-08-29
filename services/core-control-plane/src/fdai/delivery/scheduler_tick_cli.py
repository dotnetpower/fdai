"""One-shot durable scheduler entry point for a Container Apps Job."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg

from fdai.core.scheduler.run_ledger import ScheduleRunLedger
from fdai.core.scheduler.service import SchedulerRunReport, SchedulerService
from fdai.core.scheduler.store import ScheduleStore
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence.postgres_schedule_run_ledger import (
    PostgresScheduleRunLedger,
    PostgresScheduleRunLedgerConfig,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.runtime.venue import (
    bus_security_protocol,
    resolve_execution_venue,
    uses_developer_identity,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.scheduler_tick")

SCHEDULE_DSN_ENV = "FDAI_SCHEDULE_STORE_DSN"
BOOTSTRAP_SERVERS_ENV = "KAFKA_BOOTSTRAP_SERVERS"
TOPIC_ENV = "FDAI_SCHEDULER_TOPIC"
INGRESS_TOPIC_ENV = "KAFKA_TOPIC_EVENTS"
TICK_TIMEOUT_ENV = "FDAI_SCHEDULER_TICK_TIMEOUT_SECONDS"
CLAIM_TIMEOUT_ENV = "FDAI_SCHEDULER_CLAIM_TIMEOUT_SECONDS"
_DEFAULT_TICK_TIMEOUT_SECONDS = 240
_DEFAULT_CLAIM_TIMEOUT_SECONDS = 600


class SchedulerJobConfigurationError(ValueError):
    """Required scheduler Job bindings are missing or outside their bounds."""


@dataclass(frozen=True, slots=True)
class SchedulerJobSettings:
    """Validated environment bindings for one scheduler Job fire."""

    dsn: str
    bootstrap_servers: str
    topic: str
    tick_timeout_seconds: int = _DEFAULT_TICK_TIMEOUT_SECONDS
    claim_timeout_seconds: int = _DEFAULT_CLAIM_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for name, value in (
            ("dsn", self.dsn),
            ("bootstrap_servers", self.bootstrap_servers),
            ("topic", self.topic),
        ):
            if not value.strip():
                raise SchedulerJobConfigurationError(
                    f"SchedulerJobSettings.{name} MUST be non-empty"
                )
        if not 1 <= self.tick_timeout_seconds <= 300:
            raise SchedulerJobConfigurationError(
                "SchedulerJobSettings.tick_timeout_seconds MUST be between 1 and 300"
            )
        if not 60 <= self.claim_timeout_seconds <= 86_400:
            raise SchedulerJobConfigurationError(
                "SchedulerJobSettings.claim_timeout_seconds MUST be between 60 and 86400"
            )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> SchedulerJobSettings:
        """Load required bindings without retaining or rendering secret values."""

        dsn = _required(environ, SCHEDULE_DSN_ENV)
        bootstrap_servers = _required(environ, BOOTSTRAP_SERVERS_ENV)
        topic = environ.get(TOPIC_ENV, "").strip() or environ.get(INGRESS_TOPIC_ENV, "").strip()
        if not topic:
            raise SchedulerJobConfigurationError(f"{TOPIC_ENV} or {INGRESS_TOPIC_ENV} is required")
        return cls(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            bootstrap_servers=bootstrap_servers,
            topic=topic,
            tick_timeout_seconds=_bounded_integer(
                environ.get(TICK_TIMEOUT_ENV, ""),
                name=TICK_TIMEOUT_ENV,
                default=_DEFAULT_TICK_TIMEOUT_SECONDS,
                minimum=1,
                maximum=300,
            ),
            claim_timeout_seconds=_bounded_integer(
                environ.get(CLAIM_TIMEOUT_ENV, ""),
                name=CLAIM_TIMEOUT_ENV,
                default=_DEFAULT_CLAIM_TIMEOUT_SECONDS,
                minimum=60,
                maximum=86_400,
            ),
        )


async def execute_scheduler_tick(
    *,
    settings: SchedulerJobSettings,
    store: ScheduleStore,
    run_ledger: ScheduleRunLedger,
    event_bus: EventBus,
    now: datetime | None = None,
) -> SchedulerRunReport:
    """Reconcile abandoned claims and run one bounded shadow scheduler pass."""

    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("scheduler tick time MUST be timezone-aware")
    async with asyncio.timeout(settings.tick_timeout_seconds):
        await run_ledger.reconcile_stale(
            before=observed_at - timedelta(seconds=settings.claim_timeout_seconds),
            at=observed_at,
        )
        return await SchedulerService(
            store=store,
            event_bus=event_bus,
            run_ledger=run_ledger,
            topic=settings.topic,
        ).run_once(now=observed_at)


async def run_once(environ: Mapping[str, str] | None = None) -> SchedulerRunReport:
    """Compose PostgreSQL and Event Hubs adapters for one scheduled invocation."""

    settings = SchedulerJobSettings.from_environ(os.environ if environ is None else environ)
    store = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=settings.dsn))
    run_ledger = PostgresScheduleRunLedger(config=PostgresScheduleRunLedgerConfig(dsn=settings.dsn))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    ) as http_client:
        identity = _build_identity(http_client)
        venue = resolve_execution_venue()
        bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=settings.bootstrap_servers,
                security_protocol=bus_security_protocol(venue),
                client_id="fdai-scheduler-job",
            ),
        )
        try:
            return await execute_scheduler_tick(
                settings=settings,
                store=store,
                run_ledger=run_ledger,
                event_bus=bus,
            )
        finally:
            await bus.close()


def report_summary(report: SchedulerRunReport) -> dict[str, object]:
    """Return a bounded summary without task ids, payloads, endpoints, or errors."""

    error_kinds = tuple(sorted({detail.partition(":")[0] for _, detail in report.publish_errors}))
    return {
        "status": "publish_failed" if report.publish_errors else "completed",
        "fired": report.fired,
        "duplicates_suppressed": report.duplicates_suppressed,
        "publish_error_count": len(report.publish_errors),
        "publish_error_kinds": list(error_kinds),
        "execution_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Run one tick and return stable configuration, retry, or success status."""

    arguments = argv if argv is not None else sys.argv[1:]
    if arguments:
        print(json.dumps({"status": "invalid_arguments"}, sort_keys=True))
        return 2
    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    try:
        report = asyncio.run(run_once())
    except SchedulerJobConfigurationError as exc:
        _LOGGER.error(
            "scheduler_tick_configuration_invalid", extra={"error_kind": type(exc).__name__}
        )
        print(json.dumps({"status": "configuration_required"}, sort_keys=True))
        return 2
    except (TimeoutError, psycopg.Error, OSError) as exc:
        _LOGGER.error("scheduler_tick_failed", extra={"error_kind": type(exc).__name__})
        print(
            json.dumps(
                {"status": "retry_required", "error_kind": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1

    summary: dict[str, Any] = report_summary(report)
    _LOGGER.info("scheduler_tick_complete", extra=summary)
    print(json.dumps(summary, sort_keys=True))
    return 1 if report.publish_errors else 0


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SchedulerJobConfigurationError(f"{name} is required")
    return value


def _bounded_integer(
    raw: str,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    text = raw.strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError as exc:
        raise SchedulerJobConfigurationError(f"{name} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise SchedulerJobConfigurationError(f"{name} MUST be between {minimum} and {maximum}")
    return value


def _build_identity(http_client: httpx.AsyncClient) -> WorkloadIdentity:
    venue = resolve_execution_venue()
    if uses_developer_identity(venue):
        return AsyncAzureCliWorkloadIdentity.from_env()
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env="FDAI_MI_CLIENT_ID",
    )


if __name__ == "__main__":
    raise SystemExit(main())
