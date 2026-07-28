"""FDAI-owned composition for independently installed evaluation adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdai_evaluation_sdk import AuthorityCeiling, SideEffectClass

from fdai.core.rca import RcaReasoner
from fdai.delivery.evaluation import KubectlEvidenceClient, kubernetes_evidence_providers
from fdai.evaluation.artifacts import InMemoryArtifactBroker, InMemoryArtifactCustodySink
from fdai.evaluation.capabilities import AuthorityAxes, CapabilityAxes
from fdai.evaluation.evidence import BoundedEvaluationEvidenceCollector
from fdai.evaluation.host import (
    EvaluationHostPolicy,
    EventProcessor,
    FdaiEvaluationHost,
    InMemoryExternalValidationSink,
)

_SREGYM_CAPABILITIES = {
    "observe.kubernetes.inventory": SideEffectClass.OBSERVE,
    "observe.kubernetes.events": SideEffectClass.OBSERVE,
    "observe.metrics.query": SideEffectClass.OBSERVE,
    "observe.logs.query": SideEffectClass.OBSERVE,
    "observe.traces.query": SideEffectClass.OBSERVE,
}


@dataclass(frozen=True, slots=True)
class EvaluationRuntimeReadiness:
    """Fail-closed readiness facts for one external evaluation run."""

    adapter_id: str
    rca_reasoner_ready: bool
    kubernetes_inventory_ready: bool
    kubernetes_events_ready: bool
    shadow_only: bool = True

    @property
    def ready(self) -> bool:
        return (
            self.rca_reasoner_ready
            and self.kubernetes_inventory_ready
            and self.kubernetes_events_ready
            and self.shadow_only
        )


def build_sregym_evaluation_host(
    *,
    processor: EventProcessor,
    evidence_client: KubectlEvidenceClient,
    rca_reasoner: RcaReasoner | None,
) -> tuple[FdaiEvaluationHost, EvaluationRuntimeReadiness]:
    """Compose a shadow-only SREGym host or report why it cannot diagnose."""

    providers = kubernetes_evidence_providers(evidence_client)
    allowed = frozenset(_SREGYM_CAPABILITIES)
    shadow = AuthorityCeiling.SHADOW
    host = FdaiEvaluationHost(
        processor=processor,
        artifact_broker=InMemoryArtifactBroker(
            custody_sink=InMemoryArtifactCustodySink(),
        ),
        validation_sink=InMemoryExternalValidationSink(),
        evidence_collector=BoundedEvaluationEvidenceCollector(providers=providers),
        policy=EvaluationHostPolicy(
            capability_catalog=_SREGYM_CAPABILITIES,
            capability_axes=CapabilityAxes(*((allowed,) * 6)),
            authority_axes=AuthorityAxes(*((shadow,) * 6)),
            target_resource_types={"kubernetes.namespace": "kubernetes.namespace"},
            max_tasks=3,
            max_concurrency=1,
        ),
    )
    readiness = sregym_evaluation_readiness(
        evidence_client=evidence_client,
        rca_reasoner=rca_reasoner,
    )
    return host, readiness


def sregym_evaluation_readiness(
    *,
    evidence_client: KubectlEvidenceClient,
    rca_reasoner: RcaReasoner | None,
) -> EvaluationRuntimeReadiness:
    """Evaluate composition prerequisites without constructing the control loop."""

    providers = kubernetes_evidence_providers(evidence_client)
    return EvaluationRuntimeReadiness(
        adapter_id="sregym",
        rca_reasoner_ready=rca_reasoner is not None,
        kubernetes_inventory_ready="observe.kubernetes.inventory" in providers,
        kubernetes_events_ready="observe.kubernetes.events" in providers,
    )


def readiness_payload(readiness: EvaluationRuntimeReadiness) -> dict[str, Any]:
    """Return a stable machine-readable readiness projection."""

    return {
        "adapter_id": readiness.adapter_id,
        "ready": readiness.ready,
        "shadow_only": readiness.shadow_only,
        "checks": {
            "rca_reasoner": readiness.rca_reasoner_ready,
            "kubernetes_inventory": readiness.kubernetes_inventory_ready,
            "kubernetes_events": readiness.kubernetes_events_ready,
        },
    }


__all__ = [
    "EvaluationRuntimeReadiness",
    "build_sregym_evaluation_host",
    "readiness_payload",
    "sregym_evaluation_readiness",
]
