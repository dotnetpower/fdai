"""Construct analyzer tick dependencies from validated environment state."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager

from fdai_service_contracts.resource_availability_settings import (
    RESOURCE_AVAILABILITY_SETTING_KEY,
    ResourceAvailabilitySettings,
)

from fdai.core.investigation import AnalyzerFinding, InvestigationCoordinator, default_analyzers
from fdai.core.investigation.analyzer import ResourceAnalyzer
from fdai.core.investigation.kubernetes_pod_status import POD_STATUS_FAULT_SIGNALS
from fdai.delivery.analyzer_inventory import (
    AnalyzerInventorySources,
    build_analyzer_inventory_sources,
)
from fdai.delivery.analyzer_metric_provider import AnalyzerMetricProvider
from fdai.delivery.analyzer_receipt_store import StateStoreAnalyzerReceiptStore
from fdai.delivery.analyzer_recovery import RecoveryAwareAnalyzer
from fdai.delivery.analyzer_telemetry_admission import discovered_telemetry_holds
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.analyzer_tick_cli_config import INVENTORY_DSN_ENV, STATE_STORE_DSN_ENV
from fdai.delivery.azure.analyzer_publication_reconciler import (
    KafkaAnalyzerPublicationReconciler,
)
from fdai.delivery.azure.event_bus import EventHubsKafkaBusConfig
from fdai.delivery.detection_lifecycle_state import DetectionLifecycleRecorder
from fdai.delivery.persistence import (
    PostgresStateStore,
    PostgresStateStoreConfig,
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.delivery.persistence.postgres_idempotency import PostgresIdempotencyStoreConfig
from fdai.delivery.pod_evidence_binding import (
    build_pod_analyzer,
)
from fdai.delivery.pod_runtime_binding import build_production_pod_analyzer
from fdai.delivery.resource_availability_binding import build_resource_availability_analyzers
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.venue import ExecutionVenue, bus_security_protocol, uses_workload_identity
from fdai.shared.providers.metric import MetricProvider
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.analyzer_tick")
_ANALYZER_MAX_CONCURRENCY = 4


async def read_availability_target_policy() -> dict[str, str]:
    """Read explicit availability targets without borrowing inventory credentials."""
    if not os.environ.get(STATE_STORE_DSN_ENV, "").strip():
        _LOGGER.info(
            "analyzer_availability_policy_unavailable",
            extra={"reason": "state_store_unbound"},
        )
        return {}
    receipts = build_receipt_store()
    try:
        values, _ = await RuntimeSettingsService(
            store=receipts.state_store, env=os.environ, durable=True
        ).effective_values_with_revision()
        policy = ResourceAvailabilitySettings.model_validate(
            values[RESOURCE_AVAILABILITY_SETTING_KEY]
        )
        return (
            {ref: entry.resource_type for ref, entry in policy.resources.items()}
            if policy.enabled
            else {}
        )
    finally:
        await receipts.aclose()


class _AdmittedMetricAnalyzer:
    def __init__(self, analyzer: ResourceAnalyzer, allowed_refs: frozenset[str]) -> None:
        self._analyzer = analyzer
        self._allowed_refs = allowed_refs

    @property
    def resource_kind(self) -> str:
        return self._analyzer.resource_kind

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        if resource_ref not in self._allowed_refs:
            _LOGGER.info(
                "analyzer_metric_target_held",
                extra={
                    "resource_kind": self.resource_kind,
                    "reason": "telemetry_source_unavailable",
                },
            )
            return ()
        return await self._analyzer.analyze(
            resource_ref=resource_ref, window_seconds=window_seconds
        )


class _AnalyzerDecisionEvidenceAdmissionProvider(StateStoreDecisionEvidenceAdmissionProvider):
    """Own the analyzer-only Postgres store for one target-resolution pass."""

    def __init__(self, store: PostgresStateStore) -> None:
        super().__init__(store=store)
        self._owned_store = store

    async def aclose(self) -> None:
        await self._owned_store.aclose()


def build_inventory_sources() -> AnalyzerInventorySources | None:
    """Bind logical and provider-native inventory views from one DSN."""

    return build_analyzer_inventory_sources(os.environ.get(INVENTORY_DSN_ENV, ""))


def build_publication_ledger() -> PostgresAnalyzerPublicationLedger:
    """Bind restart-durable publication suppression in every execution venue."""

    dsn = os.environ.get(STATE_STORE_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(
            f"{STATE_STORE_DSN_ENV} is required for duplicate-safe analyzer publication"
        )
    return PostgresAnalyzerPublicationLedger(
        config=PostgresIdempotencyStoreConfig(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        )
    )


def build_receipt_store() -> StateStoreAnalyzerReceiptStore:
    """Bind the bounded receipt projection to the tracked-state database."""

    dsn = os.environ.get(STATE_STORE_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(f"{STATE_STORE_DSN_ENV} is required for analyzer finding receipts")
    return StateStoreAnalyzerReceiptStore(
        PostgresStateStore(
            config=PostgresStateStoreConfig(
                dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
            )
        )
    )


def build_publication_reconciler(
    bootstrap_servers: str,
    venue: ExecutionVenue,
    identity: WorkloadIdentity,
) -> KafkaAnalyzerPublicationReconciler:
    """Bind bounded positive readback to the finding bus endpoint."""

    return KafkaAnalyzerPublicationReconciler(
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=bootstrap_servers,
            security_protocol=bus_security_protocol(venue),
        ),
        identity=identity if uses_workload_identity(venue) else None,
    )


def build_lifecycle_recorder() -> DetectionLifecycleRecorder:
    """Bind the tracked-state writer that keeps Pod failure history readable."""

    dsn = os.environ.get(STATE_STORE_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(f"{STATE_STORE_DSN_ENV} is required for Pod lifecycle projection")
    return DetectionLifecycleRecorder(
        PostgresStateStore(
            config=PostgresStateStoreConfig(
                dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
            )
        )
    )


def build_decision_evidence_admission_provider() -> (
    StateStoreDecisionEvidenceAdmissionProvider | None
):
    """Bind the durable admission lookup used by target selection."""

    dsn = os.environ.get(STATE_STORE_DSN_ENV, "").strip()
    if not dsn:
        _LOGGER.warning(
            "analyzer_decision_evidence_unavailable",
            extra={"reason": "state_store_dsn_absent"},
        )
        return None
    return _AnalyzerDecisionEvidenceAdmissionProvider(
        PostgresStateStore(
            config=PostgresStateStoreConfig(
                dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
            )
        )
    )


def build_analyzer_coordinator(
    metric_provider: MetricProvider,
    *,
    targets: tuple[AnalyzerTarget, ...],
    pod_analyzer: ResourceAnalyzer | None = None,
    additional_analyzers: tuple[ResourceAnalyzer, ...] = (),
    state_store: StateStore | None = None,
    metric_target_refs: frozenset[str] | None = None,
) -> InvestigationCoordinator:
    """Compose every production analyzer this venue can ground."""

    analyzer_provider = AnalyzerMetricProvider(
        metric_provider,
        targets=tuple(target for target in targets if target.resource_kind != "kubernetes_pod"),
        normalize_provider_ref=str.casefold,
    )
    analyzers = list(default_analyzers(analyzer_provider))
    for index, analyzer in enumerate(analyzers):
        if state_store is not None and analyzer.resource_kind in {
            "virtual_machine",
            "virtual_machine_scale_set",
        }:
            analyzers[index] = RecoveryAwareAnalyzer(analyzer, state_store, ("host_cpu",))
    if metric_target_refs is not None:
        analyzers = [
            _AdmittedMetricAnalyzer(analyzer, metric_target_refs) for analyzer in analyzers
        ]
    selected_pod = pod_analyzer or build_pod_analyzer()
    if selected_pod is not None:
        analyzers.append(
            RecoveryAwareAnalyzer(selected_pod, state_store, POD_STATUS_FAULT_SIGNALS)
            if state_store is not None
            else selected_pod
        )
    return InvestigationCoordinator(
        analyzers=(*analyzers, *additional_analyzers),
        max_concurrency=_ANALYZER_MAX_CONCURRENCY,
    )


@asynccontextmanager
async def build_production_coordinator(
    metric_provider: MetricProvider,
    *,
    targets: tuple[AnalyzerTarget, ...],
    configured: Sequence[AnalyzerTarget],
    monitor_workspace_id: str | None,
    inventory: AnalyzerInventorySources | None,
    inventory_generation: str | None,
    receipt_store: StateStoreAnalyzerReceiptStore,
    identity: WorkloadIdentity,
) -> AsyncIterator[InvestigationCoordinator]:
    """Bind metric, Pod and availability detectors to their authoritative sources.

    A metric detector is held for a discovered resource whose telemetry source is unbound,
    while explicitly pinned targets and the independent availability detector still run.
    """
    telemetry_holds = discovered_telemetry_holds(monitor_workspace_id=monitor_workspace_id)
    pinned = {(item.resource_kind, item.resource_ref.casefold()) for item in configured}
    metric_target_refs = frozenset(
        target.resource_ref
        for target in targets
        if target.resource_type not in telemetry_holds
        or (target.resource_kind, target.resource_ref.casefold()) in pinned
        or (target.resource_kind, (target.provider_query_ref or "").casefold()) in pinned
    )
    async with AsyncExitStack() as observer_stack:
        pod_binding = await build_production_pod_analyzer(
            stack=observer_stack,
            identity=identity,
            dsn=os.environ.get(INVENTORY_DSN_ENV, ""),
            environ=os.environ,
        )
        availability = await build_resource_availability_analyzers(
            settings=RuntimeSettingsService(
                store=receipt_store.state_store, env=os.environ, durable=True
            ),
            inventory=inventory.provider_references if inventory is not None else None,
            inventory_generation=inventory_generation,
            targets=targets,
            state_store=receipt_store.state_store,
        )
        for detector, reason in (
            ("kubernetes_pod", pod_binding.unavailable_reason),
            ("resource_availability", availability.unavailable_reason),
        ):
            if reason:
                _LOGGER.info(
                    "analyzer_binding_unavailable", extra={"detector": detector, "reason": reason}
                )
        yield build_analyzer_coordinator(
            metric_provider,
            targets=targets,
            metric_target_refs=metric_target_refs,
            pod_analyzer=pod_binding.analyzer,
            additional_analyzers=tuple(availability.analyzers),
            state_store=receipt_store.state_store,
        )


__all__ = [
    "build_analyzer_coordinator",
    "build_decision_evidence_admission_provider",
    "build_inventory_sources",
    "build_production_coordinator",
    "build_lifecycle_recorder",
    "build_publication_ledger",
    "build_publication_reconciler",
    "build_receipt_store",
    "read_availability_target_policy",
]
