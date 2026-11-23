"""Opt-in runtime binding for Azure Service Health signal detection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.azure.service_health import AzureServiceHealthConfig, AzureServiceHealthReader
from fdai.delivery.azure.service_health_signals import ServiceHealthSignalJob
from fdai.delivery.persistence import PostgresReportSignalStore, PostgresReportSignalStoreConfig

ENABLE_ENV = "FDAI_SERVICE_HEALTH_SIGNALS_ENABLED"
_INTERVAL_ENV = "FDAI_SERVICE_HEALTH_SIGNALS_INTERVAL_SECONDS"


def service_health_signals_enabled(environment: Mapping[str, str]) -> bool:
    return environment.get(ENABLE_ENV, "").strip() == "1"


def build_service_health_signal_job(
    *,
    environment: Mapping[str, str],
    identity: Any,
    http_client: Any,
) -> ServiceHealthSignalJob | None:
    """Bind detection only when explicitly enabled and fully server-configured."""

    if not service_health_signals_enabled(environment):
        return None
    subscription_id = environment.get("AZURE_SUBSCRIPTION_ID", "").strip()
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if identity is None or http_client is None or not subscription_id or not dsn:
        raise RuntimeError(
            f"{ENABLE_ENV}=1 requires an identity, HTTP client, AZURE_SUBSCRIPTION_ID, "
            "and FDAI_STATE_STORE_DSN"
        )
    raw_interval = environment.get(_INTERVAL_ENV, "").strip()
    try:
        interval = float(raw_interval) if raw_interval else 300.0
    except ValueError as exc:
        raise RuntimeError(f"{_INTERVAL_ENV} MUST be a number") from exc
    return ServiceHealthSignalJob(
        reader=AzureServiceHealthReader(
            identity=identity,
            http_client=http_client,
            config=AzureServiceHealthConfig(subscription_id=subscription_id),
        ),
        writer=PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(dsn=dsn)),
        interval_seconds=interval,
    )


__all__ = ["ENABLE_ENV", "build_service_health_signal_job", "service_health_signals_enabled"]
