"""Run one accountable frozen catalog review through the deployed Pantheon bus."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from fdai.agents import (
    CatalogReviewBindings,
    Mimir,
    PantheonRuntime,
    Saga,
    StateStoreAuditChainAdapter,
)
from fdai.core.case_history import CaseHistoryMaterializer, OperationalCaseInput
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.state_store_case_artifacts import (
    StateStoreCaseHistoryArtifactStore,
)
from fdai.delivery.persistence.state_store_case_history import (
    StateStoreCaseHistoryMetadataStore,
)
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore

_RAW_TOPIC = "catalog-review.ingress"


@dataclass(frozen=True, slots=True)
class CatalogReviewPantheonResult:
    publication: Any
    audit_digest: str
    durable_intent_verified: bool
    durable_terminal_verified: bool


@dataclass(frozen=True, slots=True)
class CatalogReviewPantheonDependencies:
    bus: EventBus
    state_store: StateStore
    durable_transport: bool
    durable_state_store: bool
    consumer_join_seconds: float


def build_deployed_catalog_review_dependencies(
    *,
    environment: dict[str, str],
    http_client: httpx.AsyncClient,
) -> CatalogReviewPantheonDependencies:
    """Build only the deployed Kafka and PostgreSQL implementations."""

    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    bootstrap = environment.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    physical_topic = environment.get("KAFKA_TOPIC_EVENTS", "").strip()
    if not dsn or not bootstrap or not physical_topic:
        raise RuntimeError("catalog review requires durable StateStore and Kafka bindings")
    identity = ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        env=dict(environment),
    )
    transport = EventHubsKafkaBus(
        identity=identity,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=bootstrap,
            security_protocol="SASL_SSL",
            client_id="fdai-catalog-review",
            auto_offset_reset="latest",
        ),
    )
    return CatalogReviewPantheonDependencies(
        bus=MultiplexedEventBus(
            bus=transport,
            logical_topics=frozenset((*RUNTIME_LOGICAL_TOPICS, _RAW_TOPIC)),
            physical_topic=physical_topic,
        ),
        state_store=PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn)),
        durable_transport=True,
        durable_state_store=True,
        consumer_join_seconds=12.0,
    )


async def run_catalog_review_pantheon(
    *,
    dependencies: CatalogReviewPantheonDependencies,
    bindings: CatalogReviewBindings,
    cases: tuple[OperationalCaseInput, ...],
    source_revision: str,
    timeout_seconds: int,
) -> CatalogReviewPantheonResult:
    """Publish raw cases and require Muninn, Norns, Mimir, and Saga closure."""

    if not dependencies.durable_transport:
        raise RuntimeError("catalog review rejects an in-memory event bus")
    if not dependencies.durable_state_store:
        raise RuntimeError("catalog review requires durable StateStore and Saga audit")
    audit_chain = StateStoreAuditChainAdapter(store=dependencies.state_store)
    saga = Saga(
        audit_chain=audit_chain,
        durable_state_store=dependencies.state_store,
    )
    if not saga.durable_audit:
        raise RuntimeError("catalog review requires durable Saga audit")
    materializer = CaseHistoryMaterializer(
        metadata=StateStoreCaseHistoryMetadataStore(store=dependencies.state_store),
        artifacts=StateStoreCaseHistoryArtifactStore(store=dependencies.state_store),
    )
    runtime = PantheonRuntime.build(
        provider=dependencies.bus,
        raw_event_topic=_RAW_TOPIC,
        consumer_group_prefix=f"fdai-catalog-review-{source_revision[:12]}",
        saga=saga,
        muninn_state_store=dependencies.state_store,
        huginn_state_store=dependencies.state_store,
        case_history_materializer=materializer,
        catalog_review=bindings,
    )
    task = asyncio.create_task(runtime.run(), name="catalog-review-pantheon")
    try:
        if dependencies.consumer_join_seconds:
            await asyncio.sleep(dependencies.consumer_join_seconds)
        for case in cases:
            identity = case.case_identity_digest
            await dependencies.bus.publish(
                _RAW_TOPIC,
                identity,
                {
                    "event_id": f"catalog-review-{identity}",
                    "idempotency_key": f"catalog-review-{identity}",
                    "source": "frozen-catalog-review",
                    "event_type": "case_history.operational_case.v1",
                    "attributes": case.to_mapping(),
                    "occurred_at": case.event_time_cutoff.isoformat(),
                },
            )
        publication, entries = await _wait_for_terminal(
            runtime=runtime,
            saga=saga,
            task=task,
            timeout_seconds=timeout_seconds,
        )
        audit_chain.verify()
        if await dependencies.state_store.verify_chain() is not True:
            raise RuntimeError("catalog review durable audit chain verification failed")
        entry_hashes = tuple(sorted(entry.entry_hash for entry in entries))
        return CatalogReviewPantheonResult(
            publication=publication,
            audit_digest=hashlib.sha256(
                json.dumps(entry_hashes, separators=(",", ":")).encode()
            ).hexdigest(),
            durable_intent_verified=any(
                entry.principal == "Muninn" and entry.topic == "object.context-index"
                for entry in entries
            ),
            durable_terminal_verified=any(
                entry.principal == "Mimir" and entry.topic == "object.rule" for entry in entries
            ),
        )
    finally:
        await runtime.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        close = getattr(dependencies.bus, "close", None)
        if callable(close):
            await close()


async def _wait_for_terminal(
    *,
    runtime: PantheonRuntime,
    saga: Saga,
    task: asyncio.Task[None],
    timeout_seconds: int,
) -> tuple[Any, list[Any]]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            exception = task.exception()
            if exception is not None:
                raise RuntimeError("catalog review Pantheon consumer failed") from exception
        mimir = runtime.agents.get("Mimir")
        if not isinstance(mimir, Mimir):
            raise RuntimeError("catalog review Mimir binding is unavailable")
        receipts = mimir.catalog_review_publication_receipts()
        entries = list(saga.audit_chain.entries)
        intent = any(
            entry.principal == "Muninn" and entry.topic == "object.context-index"
            for entry in entries
        )
        terminal = any(
            entry.principal == "Mimir" and entry.topic == "object.rule" for entry in entries
        )
        if len(receipts) == 1 and intent and terminal:
            return receipts[0], entries
        await asyncio.sleep(0.1)
    raise TimeoutError("catalog review Pantheon deadline expired")


__all__ = [
    "CatalogReviewPantheonDependencies",
    "CatalogReviewPantheonResult",
    "build_deployed_catalog_review_dependencies",
    "run_catalog_review_pantheon",
]
