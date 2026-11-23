"""Opt-in runtime binding for Azure Service Health signal detection."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fdai.core.ontology_platform.service_health_queries import ServiceHealthReader
from fdai.delivery.azure.service_health_signals import ServiceHealthSignalJob
from fdai.delivery.persistence import PostgresReportSignalStore, PostgresReportSignalStoreConfig

ENABLE_ENV = "FDAI_SERVICE_HEALTH_SIGNALS_ENABLED"
_INTERVAL_ENV = "FDAI_SERVICE_HEALTH_SIGNALS_INTERVAL_SECONDS"


def build_service_health_signal_job(
    environment: Mapping[str, str],
    reader: ServiceHealthReader | None,
) -> ServiceHealthSignalJob | None:
    """Bind detection only when explicitly enabled and fully server-configured."""

    if environment.get(ENABLE_ENV, "").strip() != "1":
        return None
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if reader is None or not dsn:
        raise RuntimeError(
            f"{ENABLE_ENV}=1 requires an Azure identity, AZURE_SUBSCRIPTION_ID, "
            "and FDAI_STATE_STORE_DSN"
        )
    raw_interval = environment.get(_INTERVAL_ENV, "").strip()
    try:
        interval = float(raw_interval) if raw_interval else 300.0
    except ValueError as exc:
        raise RuntimeError(f"{_INTERVAL_ENV} MUST be a number") from exc
    return ServiceHealthSignalJob(
        reader=reader,
        writer=PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(dsn=dsn)),
        interval_seconds=interval,
    )


def schedule_service_health_signals(config: Any) -> asyncio.Task[None] | None:
    """Supervise the detection loop only when its job is bound."""

    job = config.service_health_signal_job
    if job is None:
        return None
    return asyncio.create_task(
        config.readiness.run_when_ready(config.stop, lambda: job.run(config.stop)),
        name="azure-service-health-signals",
    )


__all__ = ["ENABLE_ENV", "build_service_health_signal_job", "schedule_service_health_signals"]
