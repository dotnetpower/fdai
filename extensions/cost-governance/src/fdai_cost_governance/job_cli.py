"""Container-job entrypoints for activation-gated Cost Governance work."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Literal, cast

import httpx
from azure.identity.aio import AzureCliCredential
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.cost_sample_publisher import EventBusCostSamplePublisher
from fdai.delivery.persistence.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceStore,
)

from .azure_focus import (
    AzureFocusObservationAdapter,
    CostHttpResponse,
    CostReadCredential,
)
from .scheduled_analytics import (
    AzureScheduledAnalyticsSource,
    ScheduledAnalyticsResult,
    run_scheduled_analytics,
)
from .service import CostAnalyzerService, CostCollectorService, CostJobConfig

_ARM_AUDIENCE = "https://management.azure.com/.default"
_COST_RETRY_AFTER_HEADERS = (
    "retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after",
)


class _ManagedIdentityCostCredential:
    def __init__(self, identity: ManagedIdentityWorkloadIdentity) -> None:
        self._identity = identity

    async def access_token(self, *, deadline_at: datetime) -> str:
        if datetime.now(UTC) >= deadline_at:
            raise TimeoutError("Cost Management credential deadline expired")
        return (await self._identity.get_token(_ARM_AUDIENCE)).token


class _AzureCliCostCredential:
    def __init__(self, credential: AzureCliCredential) -> None:
        self._credential = credential

    async def access_token(self, *, deadline_at: datetime) -> str:
        if datetime.now(UTC) >= deadline_at:
            raise TimeoutError("Cost Management credential deadline expired")
        return cast(str, (await self._credential.get_token(_ARM_AUDIENCE)).token)


class _HttpxCostTransport:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object],
        max_bytes: int,
        deadline_at: datetime,
    ) -> CostHttpResponse:
        timeout = (deadline_at - datetime.now(UTC)).total_seconds()
        if timeout <= 0:
            raise TimeoutError("Cost Management request deadline expired")
        response = await self._client.post(
            url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )
        body = await response.aread()
        if len(body) > max_bytes:
            raise RuntimeError("Cost Management response exceeded byte budget")
        return CostHttpResponse(
            status_code=response.status_code,
            body=body,
            retry_after_seconds=_cost_retry_after_seconds(response.headers),
        )


def _cost_retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """Return the longest valid provider retry delay without retaining raw headers."""

    normalized = {name.casefold(): value for name, value in headers.items()}
    delays: list[float] = []
    for name in _COST_RETRY_AFTER_HEADERS:
        value = normalized.get(name)
        if value is None:
            continue
        try:
            delay = float(value)
        except ValueError:
            if name != "retry-after":
                continue
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                continue
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            delay = max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
        if math.isfinite(delay) and delay >= 0:
            delays.append(delay)
    return max(delays) if delays else None


def collector_main() -> None:
    """Run one bounded collector pass from deployment-owned environment config."""

    raise SystemExit(asyncio.run(_run_collector(os.environ)))


def analyzer_main() -> None:
    """Run one bounded analyzer/publisher pass from environment config."""

    raise SystemExit(asyncio.run(_run_analyzer(os.environ)))


def analytics_main() -> None:
    """Run the shared bounded analytics command once or on a local schedule."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=_positive_int(os.environ, "FDAI_COST_ANALYTICS_INTERVAL_SECONDS", 3600),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=_positive_int(os.environ, "FDAI_COST_ANALYTICS_DAYS", 7),
    )
    args = parser.parse_args()
    if args.interval_seconds < 1 or not 1 <= args.days <= 31:
        parser.error("analytics interval must be positive and days must be in [1, 31]")
    raise SystemExit(
        asyncio.run(
            _run_analytics_loop(
                os.environ,
                days=args.days,
                interval_seconds=args.interval_seconds,
                loop=args.loop,
            )
        )
    )


async def _run_analytics_loop(
    env: Mapping[str, str],
    *,
    days: int,
    interval_seconds: int,
    loop: bool,
) -> int:
    while True:
        result = await run_analytics_from_environment(env, days=days)
        receipt = result.receipt
        event = _analytics_event(
            receipt.status.value,
            retained_snapshot_current=result.retained_snapshot_current,
        )
        print(
            " ".join(
                (
                    datetime.now(UTC).isoformat(),
                    "service=cost-governance-analytics",
                    f"event={event}",
                    f"status={receipt.status.value}",
                    (
                        "retained_snapshot=current"
                        if result.retained_snapshot_current
                        else "retained_snapshot=none"
                    ),
                    f"run_id={receipt.run_id}",
                )
            ),
            flush=True,
        )
        if not loop:
            return 0 if receipt.status.value in {"complete", "disabled"} else 1
        await asyncio.sleep(interval_seconds)


def _analytics_event(status: str, *, retained_snapshot_current: bool = False) -> str:
    return (
        "ready"
        if status in {"complete", "partial", "disabled"} or retained_snapshot_current
        else "waiting"
    )


async def run_analytics_from_environment(
    env: Mapping[str, str],
    *,
    days: int,
) -> ScheduledAnalyticsResult:
    scope_id = _required(env, "FDAI_COST_SCOPE_ID")
    store = PostgresCostGovernanceStore(
        config=PostgresCostGovernanceConfig(
            dsn=_required(env, "FDAI_COST_STORE_DSN"),
        )
    )
    activation = await store.read_cost_activation("cost-governance")
    release_id = env.get("FDAI_COST_ONTOLOGY_RELEASE_ID", "").strip()
    release_digest = env.get("FDAI_COST_ONTOLOGY_RELEASE_DIGEST", "").strip()
    if activation is not None:
        release_id = release_id or activation.ontology_release_id
        release_digest = release_digest or activation.ontology_release_digest
    config = CostJobConfig(
        package_id="cost-governance",
        ontology_release_id=release_id or "unavailable",
        ontology_release_digest=release_digest or f"sha256:{'0' * 64}",
        known_service_ids=frozenset({"scheduled-analytics"}),
        attempt_timeout=timedelta(
            seconds=_positive_int(env, "FDAI_COST_ATTEMPT_TIMEOUT_SECONDS", 120)
        ),
    )
    venue_value = env.get("FDAI_EXECUTION_VENUE", "deployed").strip()
    if venue_value not in {"local", "deployed"}:
        raise ValueError("FDAI_EXECUTION_VENUE MUST be local or deployed")
    venue: Literal["local", "deployed"] = "local" if venue_value == "local" else "deployed"
    bus = None
    cli_credential = None
    async with httpx.AsyncClient(headers={"Accept": "application/json"}) as client:
        if venue == "local":
            cli_credential = AzureCliCredential()
            credential: CostReadCredential = _AzureCliCostCredential(cli_credential)
            workload_identity = None
        else:
            workload_identity = ManagedIdentityWorkloadIdentity.from_env(
                http_client=client,
                env=env,
                client_id_env="FDAI_COST_COLLECTION_MI_CLIENT_ID",
            )
            credential = _ManagedIdentityCostCredential(workload_identity)
        publisher = None
        bootstrap = env.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
        topic = (
            env.get("FDAI_COST_RAW_EVENT_TOPIC", "").strip()
            or env.get("KAFKA_TOPIC_EVENTS", "").strip()
        )
        if bootstrap and topic:
            bus = EventHubsKafkaBus(
                config=EventHubsKafkaBusConfig(
                    bootstrap_servers=bootstrap,
                    security_protocol="PLAINTEXT" if venue == "local" else "SASL_SSL",
                    client_id=f"fdai-{venue}-cost-analytics",
                ),
                identity=workload_identity,
            )
            publisher = EventBusCostSamplePublisher(bus=bus, topic=topic)
        try:
            result = await run_scheduled_analytics(
                config=config,
                scope_id=scope_id,
                venue=venue,
                days=days,
                source=AzureScheduledAnalyticsSource(client=client, credential=credential),
                store=store,
                publisher=publisher,
            )
            if result.receipt.status.value == "failed":
                return replace(
                    result,
                    retained_snapshot_current=(
                        await store.current_cost_analytics_snapshot_available(
                            scope_id=scope_id,
                            now=datetime.now(UTC),
                            freshness=timedelta(days=2),
                        )
                    ),
                )
            return result
        finally:
            if bus is not None:
                await bus.close()
            if cli_credential is not None:
                await cli_credential.close()


async def _run_collector(env: Mapping[str, str]) -> int:
    config, scope_id, store = _common(env)
    if not await _activation_matches(store, config):
        print(json.dumps({"job": "collector", "status": "disabled"}, sort_keys=True))
        return 0
    end_at = datetime.now(UTC)
    start_at = end_at - timedelta(seconds=_positive_int(env, "FDAI_COST_WINDOW_SECONDS", 86400))
    async with httpx.AsyncClient() as client:
        identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=client,
            env=env,
            client_id_env="FDAI_COST_COLLECTION_MI_CLIENT_ID",
        )
        provider = AzureFocusObservationAdapter(
            transport=_HttpxCostTransport(client),
            credential=_ManagedIdentityCostCredential(identity),
            ontology_release_id=config.ontology_release_id,
            ontology_release_digest=config.ontology_release_digest,
        )
        result = await CostCollectorService(
            config=config,
            activation=store,
            provider=provider,
            store=store,
        ).collect(scope_id=scope_id, start_at=start_at, end_at=end_at)
    print(json.dumps({"job": "collector", "status": result.status}, sort_keys=True))
    return 0 if result.status in {"complete", "disabled"} else 1


async def _run_analyzer(env: Mapping[str, str]) -> int:
    config, scope_id, store = _common(env)
    if not await _activation_matches(store, config):
        print(json.dumps({"job": "analyzer", "status": "disabled"}, sort_keys=True))
        return 0
    async with httpx.AsyncClient() as client:
        identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=client,
            env=env,
            client_id_env="FDAI_COST_COLLECTION_MI_CLIENT_ID",
        )
        event_bus = EventHubsKafkaBus(
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=_required(env, "KAFKA_BOOTSTRAP_SERVERS"),
                client_id="fdai-cost-governance-analyzer",
            ),
            identity=identity,
        )
        publisher = EventBusCostSamplePublisher(
            bus=event_bus,
            topic=_required(env, "FDAI_COST_RAW_EVENT_TOPIC"),
        )
        since = datetime.now(UTC) - timedelta(
            seconds=_positive_int(env, "FDAI_COST_WINDOW_SECONDS", 86400)
        )
        result = await CostAnalyzerService(
            config=config,
            activation=store,
            store=store,
            publisher=publisher,
        ).analyze(scope_id=scope_id, since=since)
    print(json.dumps({"job": "analyzer", "status": result.status}, sort_keys=True))
    return 0 if result.status in {"complete", "disabled"} else 1


def _common(
    env: Mapping[str, str],
) -> tuple[CostJobConfig, str, PostgresCostGovernanceStore]:
    known = json.loads(_required(env, "FDAI_COST_KNOWN_SERVICE_IDS"))
    if not isinstance(known, list) or not all(isinstance(item, str) for item in known):
        raise ValueError("FDAI_COST_KNOWN_SERVICE_IDS MUST be a JSON string list")
    config = CostJobConfig(
        package_id="cost-governance",
        ontology_release_id=_required(env, "FDAI_COST_ONTOLOGY_RELEASE_ID"),
        ontology_release_digest=_required(env, "FDAI_COST_ONTOLOGY_RELEASE_DIGEST"),
        known_service_ids=frozenset(known),
        max_pages=_positive_int(env, "FDAI_COST_MAX_PAGES", 10),
        max_bytes=_positive_int(env, "FDAI_COST_MAX_BYTES", 10_000_000),
        page_size=_positive_int(env, "FDAI_COST_PAGE_SIZE", 1000),
        attempt_timeout=timedelta(
            seconds=_positive_int(env, "FDAI_COST_ATTEMPT_TIMEOUT_SECONDS", 120)
        ),
    )
    store = PostgresCostGovernanceStore(
        config=PostgresCostGovernanceConfig(
            dsn=_required(env, "FDAI_COST_STORE_DSN"),
        )
    )
    return config, _required(env, "FDAI_COST_SCOPE_ID"), store


async def _activation_matches(
    store: PostgresCostGovernanceStore,
    config: CostJobConfig,
) -> bool:
    snapshot = await store.read_cost_activation(config.package_id)
    return bool(
        snapshot
        and snapshot.available
        and snapshot.enabled
        and snapshot.ontology_release_id == config.ontology_release_id
        and snapshot.ontology_release_digest == config.ontology_release_digest
    )


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} MUST be set")
    return value


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = int(env.get(key, str(default)))
    if value < 1:
        raise ValueError(f"{key} MUST be positive")
    return value


__all__ = [
    "analytics_main",
    "analyzer_main",
    "collector_main",
    "run_analytics_from_environment",
]


if __name__ == "__main__":
    analytics_main()
