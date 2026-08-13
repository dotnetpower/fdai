"""One-shot and local-loop entry point for the shared observation campaign."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from fdai.composition import attach_metric_provider, default_container_from_env
from fdai.delivery.azure.demo_queries import default_metric_queries
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.observation_campaign import (
    AzureActivityLogObservationProbe,
    AzureCostObservationProbe,
    AzureLogAnalyticsObservationProbe,
    AzureObservationConfig,
    AzureResourceGraphObservation,
    AzureResourceGraphObservationProbe,
    PromotedInventoryObservationProbe,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.observation_campaign import ObservationCampaignRunner, ObservationProbe
from fdai.delivery.observation_probes import MetricObservationProbe
from fdai.delivery.observation_source_catalog import load_observation_source_catalog
from fdai.delivery.operational_activity import EventBusOperationalActivityPublisher
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryGraphProvider,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.config.loader import load_config_from_env
from fdai.shared.providers.workload_identity import WorkloadIdentity

_REPO_ROOT = Path(__file__).resolve().parents[5]
_LOOP_SECONDS = 60


async def run_once(*, campaign_id: str | None = None) -> dict[str, object]:
    """Compose every configured source and run one due-checked campaign."""
    venue = os.environ.get("FDAI_EXECUTION_VENUE", "deployed").strip()
    if venue not in {"local", "deployed"}:
        raise ValueError("FDAI_EXECUTION_VENUE MUST be local or deployed")
    dsn = _required_consistent(
        "FDAI_OBSERVATION_DSN",
        "FDAI_STATE_STORE_DSN",
        "FDAI_INVENTORY_DSN",
    )
    subscriptions = _csv(
        _required_consistent(
            "FDAI_OBSERVATION_SCOPES",
            "FDAI_INVENTORY_SCOPES",
            "AZURE_SUBSCRIPTION_ID",
        )
    )
    catalog_path = Path(
        os.environ.get(
            "FDAI_OBSERVATION_SOURCE_CATALOG",
            str(_REPO_ROOT / "config/observation-sources.yaml"),
        )
    )
    catalog = load_observation_source_catalog(catalog_path)
    async with httpx.AsyncClient() as client:
        identity: WorkloadIdentity = (
            AsyncAzureCliWorkloadIdentity.from_env()
            if venue == "local"
            else ManagedIdentityWorkloadIdentity.from_env(
                http_client=client,
                client_id_env="FDAI_MI_CLIENT_ID",
            )
        )
        probes = _build_probes(
            dsn=dsn,
            subscriptions=subscriptions,
            identity=identity,
            http_client=client,
        )
        bus = _build_event_bus(identity=identity, venue=venue)
        try:
            summary = await ObservationCampaignRunner(
                sources=catalog.sources,
                probes=probes,
                store=PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn)),
                publisher=EventBusOperationalActivityPublisher(event_bus=bus),
                max_concurrency=catalog.max_concurrency,
            ).run(campaign_id or _campaign_id())
        finally:
            await bus.close()
    return {
        "campaign_id": summary.campaign_id,
        "status": summary.status,
        "catalog_digest": catalog.digest,
        "sources": [
            {
                "source_id": source.source_id,
                "domain": source.domain.value,
                "status": source.status.value,
                "coverage": source.coverage.value,
                "freshness": source.freshness.value,
                "evidence_count": source.evidence_count,
                "duration_ms": source.duration_ms,
                "reason_codes": list(source.reason_codes),
                "skipped": source.skipped,
            }
            for source in summary.sources
        ],
    }


def _build_probes(
    *,
    dsn: str,
    subscriptions: tuple[str, ...],
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> dict[str, ObservationProbe]:
    management = AzureObservationConfig(
        subscription_ids=subscriptions,
        management_endpoint=os.environ.get(
            "FDAI_INVENTORY_MANAGEMENT_ENDPOINT",
            "https://management.azure.com",
        ).strip(),
        management_audience=os.environ.get(
            "FDAI_INVENTORY_MANAGEMENT_AUDIENCE",
            "https://management.azure.com/.default",
        ).strip(),
    )
    probes: dict[str, ObservationProbe] = {
        "inventory": PromotedInventoryObservationProbe(
            PostgresInventoryGraphProvider(config=PostgresInventorySnapshotStoreConfig(dsn=dsn))
        ),
        "activity-log": AzureActivityLogObservationProbe(
            config=management,
            identity=identity,
            http_client=http_client,
        ),
        "resource-health": AzureResourceGraphObservationProbe(
            config=management,
            query=AzureResourceGraphObservation.RESOURCE_HEALTH,
            identity=identity,
            http_client=http_client,
        ),
        "service-health": AzureResourceGraphObservationProbe(
            config=management,
            query=AzureResourceGraphObservation.SERVICE_HEALTH,
            identity=identity,
            http_client=http_client,
        ),
        "network-config": AzureResourceGraphObservationProbe(
            config=management,
            query=AzureResourceGraphObservation.NETWORK_CONFIG,
            identity=identity,
            http_client=http_client,
        ),
        "cost": AzureCostObservationProbe(
            config=management,
            identity=identity,
            http_client=http_client,
        ),
        "recovery": AzureResourceGraphObservationProbe(
            config=management,
            query=AzureResourceGraphObservation.RECOVERY,
            identity=identity,
            http_client=http_client,
        ),
    }
    workspace_id = os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
    if workspace_id:
        log_provider = AzureLogAnalyticsQueryProvider(
            config=AzureLogAnalyticsQueryConfig(workspace_id=workspace_id),
            identity=identity,
            http_client=http_client,
        )
        probes["logs"] = AzureLogAnalyticsObservationProbe(log_provider, source_id="logs")
        probes["guest-logs"] = AzureLogAnalyticsObservationProbe(
            log_provider,
            source_id="guest-logs",
        )
    prometheus_base_url = os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip() or None
    if workspace_id or prometheus_base_url:
        container = attach_metric_provider(
            default_container_from_env(),
            identity=identity,
            http_client=http_client,
            monitor_workspace_id=workspace_id or None,
            monitor_queries=None,
            metrics_api_queries=None,
            prometheus_base_url=prometheus_base_url,
            prometheus_queries=None,
            prometheus_audience=os.environ.get("FDAI_PROMETHEUS_AUDIENCE", "").strip() or None,
        )
        probes["metrics"] = MetricObservationProbe(
            container.metric_provider,
            metric_names=tuple(default_metric_queries()),
        )
    return probes


def _build_event_bus(*, identity: WorkloadIdentity, venue: str) -> EventHubsKafkaBus:
    config = load_config_from_env().kafka
    return EventHubsKafkaBus(
        identity=identity if venue == "deployed" else None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=config.bootstrap_servers,
            dlq_suffix=config.topic_dlq_suffix,
            security_protocol="SASL_SSL" if venue == "deployed" else "PLAINTEXT",
            client_id="fdai-observation-campaign",
        ),
    )


def _campaign_id() -> str:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dt%H%M%S%f")
    return f"campaign-{timestamp}-{secrets.token_hex(4)}"


def _required_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    raise ValueError(f"one of {', '.join(keys)} MUST be configured")


def _required_consistent(*keys: str) -> str:
    configured = {key: value for key in keys if (value := os.environ.get(key, "").strip())}
    if not configured:
        raise ValueError(f"one of {', '.join(keys)} MUST be configured")
    if len(set(configured.values())) > 1:
        raise ValueError(f"configured aliases {', '.join(configured)} MUST agree")
    return next(iter(configured.values()))


def _csv(value: str) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    if not values:
        raise ValueError("observation scopes MUST be non-empty")
    return values


async def _main(argv: list[str]) -> int:
    loop = argv == ["--loop"]
    if argv and not loop:
        raise ValueError("observation campaign accepts only --loop")
    while True:
        print(json.dumps(await run_once(), sort_keys=True, separators=(",", ":")))
        if not loop:
            return 0
        await asyncio.sleep(_LOOP_SECONDS)


def main() -> None:
    """Run the campaign once for a scheduled job or continuously for local parity."""
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()


__all__ = ["main", "run_once"]
