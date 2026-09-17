"""Bounded observation-to-projection coordinator for the commerce scenario."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.investigation import AnalyzerFinding, FindingAssessment
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts import AksCommerceProjection, AksCommerceStatus

from fdai_aks_commerce.assessment import assess_aks_commerce
from fdai_aks_commerce.models import (
    AksCommerceAssessmentPolicy,
    AksCommerceEvidenceFrame,
)

PROJECTION_KEY_PREFIX = "aks-commerce:projection:v1:"


class AksCommerceObservationSource(Protocol):
    """Collect one exact, bounded evidence frame."""

    async def collect(self, service_id: str) -> AksCommerceEvidenceFrame: ...


class AksCommerceCoordinator:
    """Collect, assess, and persist one content-addressed projection."""

    def __init__(
        self,
        *,
        source: AksCommerceObservationSource,
        store: StateStore,
        policy: AksCommerceAssessmentPolicy | None = None,
        retain_newest: int = 96,
    ) -> None:
        if not 1 <= retain_newest <= 10_000:
            raise ValueError("AKS commerce retention must be in [1, 10000]")
        self._source = source
        self._store = store
        self._policy = policy
        self._retain_newest = retain_newest

    async def run_once(self, service_id: str) -> AksCommerceProjection:
        """Persist one immutable assessment and update the latest pointer."""

        frame = await self._source.collect(service_id)
        projection = assess_aks_commerce(frame, policy=self._policy)
        payload = projection.model_dump(mode="json")
        prefix = f"{PROJECTION_KEY_PREFIX}{service_id}:"
        await self._store.write_state(f"{prefix}{projection.assessment_id}", payload)
        await self._store.write_state(f"{prefix}latest", payload)
        await self._store.delete_states_beyond(prefix, retain_newest=self._retain_newest)
        return projection


class AksCommerceAnalyzer:
    """Adapt retained commerce evidence to the shared, non-executing Analyzer ingress.

    The composition root supplies exact resource-to-service bindings and severity. The shared
    AnalyzerTickRunner owns event publication, durable duplicate suppression, and reconciliation;
    this adapter owns no broker, Incident writer, agent reference, or execution credential.
    """

    def __init__(
        self,
        *,
        coordinator: AksCommerceCoordinator,
        resource_kind: str,
        service_by_resource: Mapping[str, str],
        severity: Severity,
        max_age_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not resource_kind.strip() or len(resource_kind) > 128:
            raise ValueError("AKS commerce analyzer resource kind must be bounded text")
        if not 1 <= len(service_by_resource) <= 32 or any(
            not resource.strip()
            or len(resource) > 512
            or service not in {"catalog-browse", "order-fulfillment"}
            for resource, service in service_by_resource.items()
        ):
            raise ValueError("AKS commerce analyzer requires exact supported target bindings")
        if not isinstance(severity, Severity):
            raise TypeError("AKS commerce analyzer severity must be a Severity")
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 300:
            raise ValueError("AKS commerce analyzer max age must be in [1, 300] seconds")
        self.resource_kind = resource_kind
        self._coordinator = coordinator
        self._bindings = dict(service_by_resource)
        self._severity = severity
        self._max_age = timedelta(seconds=max_age_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> tuple[AnalyzerFinding, ...]:
        """Return current degraded findings, withholding unqualified or mismatched evidence."""
        if not 1 <= window_seconds <= 86400:
            raise ValueError("AKS commerce analyzer window must be in [1, 86400] seconds")
        service_id = self._bindings.get(resource_ref)
        if service_id is None:
            raise ValueError("AKS commerce analyzer target is not configured")
        projection = await self._coordinator.run_once(service_id)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("AKS commerce analyzer clock must be timezone-aware")
        if projection.service_id != service_id or not any(
            workload.resource_ref == resource_ref for workload in projection.workloads
        ):
            raise ValueError(
                "AKS commerce assessment target does not match the configured resource"
            )
        if (
            not projection.complete
            or projection.status is AksCommerceStatus.HELD
            or projection.synthetic
            or any(metric.synthetic for metric in projection.metrics)
        ):
            raise ValueError("AKS commerce assessment is not qualified for operational ingress")
        if (
            not timedelta(0) <= now - projection.window_end <= self._max_age
            or projection.observed_at > now
            or projection.window_start < now - timedelta(seconds=window_seconds)
            or any(
                not projection.window_start <= metric.observed_at <= projection.window_end
                for metric in projection.metrics
            )
        ):
            raise ValueError("AKS commerce assessment is outside the current observation window")
        if projection.status in {AksCommerceStatus.HEALTHY, AksCommerceStatus.RECOVERED}:
            return ()
        return (
            AnalyzerFinding(
                resource_ref=resource_ref,
                resource_kind=self.resource_kind,
                signal=f"aks_commerce.{projection.status.value}",
                observation=projection.summary,
                severity=self._severity,
                occurred_at=projection.window_end,
                evidence_refs=(projection.assessment_id, *projection.evidence_refs),
                metadata={"service_id": service_id},
                assessment=FindingAssessment(
                    assessed_by="fdai.aks_commerce.assessment.v1",
                    evidence_complete=True,
                    recovery_closed=None,
                    status=projection.status.value,
                ),
            ),
        )
