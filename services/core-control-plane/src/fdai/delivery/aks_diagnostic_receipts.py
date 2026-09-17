"""Persist bounded AKS diagnostic receipts after inventory promotion."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Final

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform.aks_diagnostic_receipt_service import (
    AksDiagnosticReceiptService,
)
from fdai.core.ontology_platform.kubernetes_diagnostic_assessment import (
    AksDiagnosticContext,
    AksDiagnosticEvidenceReceipt,
)
from fdai.delivery.inventory_sync_models import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.shared.providers.state_store import StateStore

AKS_DIAGNOSTIC_RECEIPT_PREFIX: Final = "aks-diagnostic-receipt:v1:"
MAX_PROMOTION_DIAGNOSTIC_TARGETS: Final = 1_024
_KUBERNETES_SOURCE = "kubernetes_runtime_inventory"
_RECORD_TYPE = "aks_diagnostic_evidence_receipt"


class AksDiagnosticReceiptCollisionError(RuntimeError):
    """A deterministic receipt identity is already bound to different content."""


@dataclass(frozen=True, slots=True)
class StateStoreAksDiagnosticReceiptWriter:
    """Append immutable content-addressed receipts and audit them atomically."""

    store: StateStore

    async def append(
        self,
        receipt: AksDiagnosticEvidenceReceipt,
    ) -> AksDiagnosticEvidenceReceipt:
        """Create the receipt once and reject a conflicting duplicate identity."""

        receipt_value = receipt.model_dump(mode="json")
        record_digest = content_digest(receipt_value)
        key = aks_diagnostic_receipt_key(receipt)
        value: dict[str, object] = {
            "record_type": _RECORD_TYPE,
            "record_digest": record_digest,
            "receipt": receipt_value,
        }
        existing = await self.store.read_state(key)
        if existing is not None:
            if existing != value:
                raise AksDiagnosticReceiptCollisionError(
                    "AKS diagnostic receipt identity is bound to different immutable content"
                )
            return receipt
        created = await self.store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "kind": "aks_diagnostic.receipt_persisted",
                "idempotency_key": key,
                "correlation_id": receipt.audit_correlation_id,
                "target_resource_digest": _sha256(receipt.target_resource_id),
                "receipt_digest": record_digest,
                "cutoff": receipt.cutoff.isoformat(),
                "cause_claim_supported": False,
                "execution_authority": False,
            },
        )
        if created:
            return receipt
        existing = await self.store.read_state(key)
        if existing != value:
            raise AksDiagnosticReceiptCollisionError(
                "AKS diagnostic receipt identity is bound to different immutable content"
            )
        return receipt


@dataclass(frozen=True, slots=True)
class InventoryPromotionAksDiagnosticObserver:
    """Derive a bounded set of exact-target receipts from one promoted snapshot."""

    service: AksDiagnosticReceiptService
    ontology_release: str
    scope_by_cluster_ref: Mapping[str, str]
    target_limit: int = MAX_PROMOTION_DIAGNOSTIC_TARGETS

    def __post_init__(self) -> None:
        if not 1 <= self.target_limit <= MAX_PROMOTION_DIAGNOSTIC_TARGETS:
            raise ValueError("AKS diagnostic promotion target limit is invalid")

    async def observe(self, observation: PromotedInventoryObservation) -> int:
        """Persist deterministic receipts for the bounded exact Kubernetes target set."""

        if observation.recorded_at is None:
            return 0
        if observation.recorded_at.tzinfo is None:
            raise ValueError("promoted inventory observation cutoff MUST be timezone-aware")
        candidates = tuple(
            sorted(
                (
                    resource
                    for resource in observation.resources
                    if resource.type.startswith("kubernetes.")
                    and _exact_kubernetes_identity(resource.props)
                ),
                key=lambda resource: resource.resource_id,
            )
        )
        campaign_limited = len(candidates) > self.target_limit
        persisted = 0
        for target in candidates[: self.target_limit]:
            source_state = _target_source_state(
                observation.source_states,
                scope_digest=self.scope_by_cluster_ref.get(str(target.props["cluster_ref"])),
            )
            api_reachable = None
            source_cutoffs = {"inventory_snapshot": observation.recorded_at}
            source_revisions = {"inventory_snapshot": _revision_digest(observation.generation)}
            gaps = [
                "kubernetes_lifecycle_evidence_unavailable",
                "kubernetes_metric_evidence_unavailable",
                "azure_control_plane_evidence_unavailable",
            ]
            refs = [f"inventory-generation:{_sha256(observation.generation)}"]
            if (
                source_state is not None
                and source_state.status is InventoryProjectionSourceStatus.AVAILABLE
                and source_state.observed_at is not None
                and source_state.observed_at <= observation.recorded_at
            ):
                source_cutoffs[_KUBERNETES_SOURCE] = source_state.observed_at
                source_revisions[_KUBERNETES_SOURCE] = source_state.scope_digest or ""
                refs.append(f"kubernetes-scope:{source_state.scope_digest}")
                api_reachable = True
            else:
                gaps.append("kubernetes_runtime_inventory_unavailable")
            if target.type == "kubernetes.pod":
                gaps.append("kubernetes_log_evidence_unavailable")
            if not observation.complete:
                gaps.append("inventory_snapshot_incomplete")
            if campaign_limited:
                gaps.append("diagnostic_campaign_target_limit")
            await self.service.assess_and_persist(
                AksDiagnosticContext(
                    target=target,
                    related=(),
                    event_reasons=(),
                    metrics=(),
                    api_reachable=api_reachable,
                    azure_availability=None,
                    cutoff=observation.recorded_at,
                    source_cutoffs=source_cutoffs,
                    source_revisions=source_revisions,
                    evidence_refs=tuple(refs),
                    evidence_complete=False,
                    ontology_release=self.ontology_release,
                    principal_class="system",
                    audit_correlation_id=_diagnostic_correlation(
                        observation.generation,
                        target.resource_id,
                    ),
                    evidence_gaps=tuple(gaps),
                )
            )
            persisted += 1
        return persisted


def aks_diagnostic_receipt_key(receipt: AksDiagnosticEvidenceReceipt) -> str:
    """Return the bounded sortable identity key for one immutable receipt."""

    receipt_value = receipt.model_dump(mode="json")
    cutoff = receipt.cutoff.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        f"{AKS_DIAGNOSTIC_RECEIPT_PREFIX}{_sha256(receipt.target_resource_id)}:"
        f"{cutoff}:{content_digest(receipt_value)[7:]}"
    )


def _exact_kubernetes_identity(props: Mapping[str, object]) -> bool:
    return all(
        isinstance(props.get(key), str) and bool(str(props[key]).strip())
        for key in ("cluster_ref", "uid", "resource_version")
    )


def _target_source_state(
    states: tuple[InventoryProjectionSourceState, ...],
    *,
    scope_digest: str | None,
) -> InventoryProjectionSourceState | None:
    if scope_digest is None:
        return None
    return next(
        (
            state
            for state in states
            if state.source == _KUBERNETES_SOURCE and state.scope_digest == scope_digest
        ),
        None,
    )


def _diagnostic_correlation(generation: str, resource_id: str) -> str:
    return f"sha256:{_sha256(f'{generation}|{resource_id}')}"


def _revision_digest(*parts: str) -> str:
    return f"sha256:{_sha256('|'.join(parts))}"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "AKS_DIAGNOSTIC_RECEIPT_PREFIX",
    "MAX_PROMOTION_DIAGNOSTIC_TARGETS",
    "AksDiagnosticReceiptCollisionError",
    "InventoryPromotionAksDiagnosticObserver",
    "StateStoreAksDiagnosticReceiptWriter",
    "aks_diagnostic_receipt_key",
]
