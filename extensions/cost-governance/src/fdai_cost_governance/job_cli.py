"""Container-job entrypoints for activation-gated Cost Governance work."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
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
)
from .service import CostAnalyzerService, CostCollectorService, CostJobConfig

_ARM_AUDIENCE = "https://management.azure.com/.default"


class _ManagedIdentityCostCredential:
    def __init__(self, identity: ManagedIdentityWorkloadIdentity) -> None:
        self._identity = identity

    async def access_token(self, *, deadline_at: datetime) -> str:
        if datetime.now(UTC) >= deadline_at:
            raise TimeoutError("Cost Management credential deadline expired")
        return (await self._identity.get_token(_ARM_AUDIENCE)).token


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
        return CostHttpResponse(status_code=response.status_code, body=body)


def collector_main() -> None:
    """Run one bounded collector pass from deployment-owned environment config."""

    raise SystemExit(asyncio.run(_run_collector(os.environ)))


def analyzer_main() -> None:
    """Run one bounded analyzer/publisher pass from environment config."""

    raise SystemExit(asyncio.run(_run_analyzer(os.environ)))


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


__all__ = ["analyzer_main", "collector_main"]
