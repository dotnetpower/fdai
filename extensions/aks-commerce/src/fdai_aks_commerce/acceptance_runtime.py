"""Explicit one-shot runtime binding for receipt-verified acceptance Incident ingress."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai.core.investigation import InvestigationCoordinator
from fdai.delivery.analyzer_receipt_store import StateStoreAnalyzerReceiptStore
from fdai.delivery.analyzer_tick import AnalyzerTarget, AnalyzerTickReport, AnalyzerTickRunner
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.delivery.persistence.postgres_idempotency import PostgresIdempotencyStoreConfig
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts.venue import (
    ExecutionVenue,
    bus_security_protocol,
    resolve_execution_venue,
)
from pydantic import TypeAdapter

from fdai_aks_commerce.acceptance import OrderAcceptanceAnalyzer, OrderAcceptanceIntent
from fdai_aks_commerce.acceptance_receipts import (
    AcceptanceTrustBinding,
    StoredOrderAcceptanceReceiptVerifier,
)
from fdai_aks_commerce.acceptance_store import StoredOrderAcceptanceSource


@dataclass(frozen=True, slots=True)
class AcceptanceRuntimeConfig:
    """Exact deployment-owned observer binding; no execution credential or authority."""

    intent: OrderAcceptanceIntent
    trust: Mapping[str, AcceptanceTrustBinding]
    executor_identity: str
    severity: Severity
    publication_window_seconds: int

    @classmethod
    def from_json(cls, raw: str) -> AcceptanceRuntimeConfig:
        """Reject partial, oversized and unknown configuration before any provider access."""
        if not raw or len(raw) > 32_768:
            raise ValueError("FDAI_AKS_ACCEPTANCE_JSON must contain a bounded binding")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {
            "intent",
            "trust",
            "executor_identity",
            "severity",
            "publication_window_seconds",
        }:
            raise ValueError("acceptance runtime fields are incomplete or unknown")
        intent_record = value["intent"]
        if not isinstance(intent_record, dict) or set(intent_record) != {
            field.name for field in fields(OrderAcceptanceIntent)
        }:
            raise ValueError("acceptance runtime requires one exact operating intent")
        intent = TypeAdapter(OrderAcceptanceIntent).validate_json(
            json.dumps(intent_record), strict=True
        )
        window = value["publication_window_seconds"]
        if type(window) is not int or not 1 <= window <= intent.max_age_seconds:
            raise ValueError("acceptance publication window must fit the freshness bound")
        executor_identity = value["executor_identity"]
        if not isinstance(executor_identity, str) or not executor_identity:
            raise ValueError("acceptance runtime executor lineage must be explicit")
        trust_record = value["trust"]
        if not isinstance(trust_record, dict) or not 1 <= len(trust_record) <= 8:
            raise ValueError("acceptance runtime requires pinned observation keys")
        trust = {}
        for key_id, record in trust_record.items():
            if not isinstance(record, dict) or set(record) != {
                "issuer",
                "source_identity",
                "public_key_hex",
            }:
                raise ValueError("acceptance trust binding fields are invalid")
            if any(not isinstance(item, str) or not item for item in record.values()):
                raise ValueError("acceptance trust binding values must be non-empty strings")
            trust[key_id] = AcceptanceTrustBinding(
                record["issuer"],
                record["source_identity"],
                Ed25519PublicKey.from_public_bytes(bytes.fromhex(record["public_key_hex"])),
            )
        return cls(intent, trust, executor_identity, Severity(value["severity"]), window)


def build_acceptance_runner(
    *,
    config: AcceptanceRuntimeConfig,
    store: StateStore,
    event_bus: EventBus,
    publication_ledger: PostgresAnalyzerPublicationLedger,
    topic: str,
    clock: Callable[[], datetime] | None = None,
) -> AnalyzerTickRunner:
    """Bind the real stored source and signature verifier to canonical durable publication."""
    now = clock or (lambda: datetime.now(UTC))
    verifier = StoredOrderAcceptanceReceiptVerifier(
        store=store,
        intent=config.intent,
        trust=config.trust,
        executor_identity=config.executor_identity,
        clock=now,
    )
    analyzer = OrderAcceptanceAnalyzer(
        intent=config.intent,
        source=StoredOrderAcceptanceSource(store),
        verifier=verifier,
        resource_kind="kubernetes.deployment",
        severity=config.severity,
        clock=now,
    )
    return AnalyzerTickRunner(
        coordinator=InvestigationCoordinator(analyzers=(analyzer,), wall_clock=now),
        event_bus=event_bus,
        publication_ledger=publication_ledger,
        receipt_store=StateStoreAnalyzerReceiptStore(store),
        window_seconds=config.intent.max_age_seconds,
        publication_window_seconds=config.publication_window_seconds,
        topic=topic,
        clock=now,
    )


async def run_acceptance_tick(environment: Mapping[str, str] | None = None) -> AnalyzerTickReport:
    """Run a deployed read-only job; missing identity, storage or bus configuration fails closed."""
    env = environment if environment is not None else os.environ
    config = AcceptanceRuntimeConfig.from_json(env.get("FDAI_AKS_ACCEPTANCE_JSON", ""))
    venue = resolve_execution_venue(env)
    if venue is not ExecutionVenue.DEPLOYED:
        raise RuntimeError("acceptance publication requires the deployed observer venue")
    for name in (
        "FDAI_STATE_STORE_DSN",
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_TOPIC_EVENTS",
        "FDAI_MI_CLIENT_ID",
    ):
        if not env.get(name, "").strip():
            raise RuntimeError(f"{name} is required for acceptance publication")
    dsn = env["FDAI_STATE_STORE_DSN"].replace("postgresql+psycopg://", "postgresql://", 1)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    ledger = PostgresAnalyzerPublicationLedger(config=PostgresIdempotencyStoreConfig(dsn=dsn))
    async with asyncio.timeout(15), httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        identity = ManagedIdentityWorkloadIdentity.from_env(http_client=client, env=env)
        bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=env["KAFKA_BOOTSTRAP_SERVERS"],
                security_protocol=bus_security_protocol(venue),
            ),
        )
        try:
            runner = build_acceptance_runner(
                config=config,
                store=store,
                event_bus=bus,
                publication_ledger=ledger,
                topic=env["KAFKA_TOPIC_EVENTS"],
            )
            return await runner.run_once(
                (
                    AnalyzerTarget(
                        resource_ref=config.intent.resource_ref,
                        resource_kind="kubernetes.deployment",
                    ),
                )
            )
        finally:
            await bus.close()


def main() -> int:
    """Expose count-only tick status; raw observations and credentials never reach stdout."""
    try:
        report = asyncio.run(run_acceptance_tick())
    except Exception:
        print(
            json.dumps(
                {
                    "event": "aks_commerce.acceptance_tick_failed",
                    "reason": "tick_unavailable",
                    "failed": True,
                    "execution_authority": False,
                },
                sort_keys=True,
            )
        )
        return 1
    result: dict[str, Any] = {
        "targets": report.targets,
        "findings": report.findings,
        "published": report.published,
        "duplicates_suppressed": report.duplicates_suppressed,
        "failed": report.failed,
        "execution_authority": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 1 if report.failed else 0
