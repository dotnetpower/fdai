"""Construct analyzer tick dependencies from validated environment state."""

from __future__ import annotations

import logging
import os

from fdai.core.investigation import InvestigationCoordinator, default_analyzers
from fdai.delivery.analyzer_inventory import (
    AnalyzerInventorySources,
    build_analyzer_inventory_sources,
)
from fdai.delivery.analyzer_metric_provider import AnalyzerMetricProvider
from fdai.delivery.analyzer_receipt_store import StateStoreAnalyzerReceiptStore
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.analyzer_tick_cli_config import INVENTORY_DSN_ENV, STATE_STORE_DSN_ENV
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
from fdai.delivery.pod_evidence_binding import build_pod_lifecycle_evidence_source
from fdai.shared.providers.metric import MetricProvider

_LOGGER = logging.getLogger("fdai.analyzer_tick")


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
) -> InvestigationCoordinator:
    """Compose every production analyzer this venue can ground."""

    analyzer_provider = AnalyzerMetricProvider(
        metric_provider,
        targets=targets,
        normalize_provider_ref=str.casefold,
    )
    return InvestigationCoordinator(
        analyzers=default_analyzers(
            analyzer_provider,
            pod_lifecycle_evidence=build_pod_lifecycle_evidence_source(),
        )
    )


__all__ = [
    "build_analyzer_coordinator",
    "build_decision_evidence_admission_provider",
    "build_inventory_sources",
    "build_lifecycle_recorder",
    "build_publication_ledger",
    "build_receipt_store",
]
