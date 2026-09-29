"""Bind the deployment causal-evidence path into one runtime coordinator.

A deployment supplies bounded temporal series through the container (for example with
``bind_azure_operational_evidence``). The runtime completes that binding with Forseti's
single-writer ``CausalHypothesis`` projection over the runtime ontology instance store and
with the Thor ActionRun receipt resolver, unless the deployment already bound its own. The
result stays shadow and evidence-only: no causal revision grants execution authority.
"""

from __future__ import annotations

from fdai.composition import Container
from fdai.core.rca import (
    CausalHypothesisProjector,
    CausalRuntimeCoordinator,
    TemporalCausalityAnalyzer,
)
from fdai.delivery.persistence.state_store_causal_receipts import (
    StateStoreCausalInterventionReceiptVerifier,
)
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.state_store import StateStore


def build_causal_runtime_coordinator(
    *,
    container: Container,
    ontology_instance_store: OntologyInstanceStore | None,
    audit_store: StateStore,
    method_version: str,
) -> CausalRuntimeCoordinator | None:
    """Return the bound causal coordinator, or ``None`` when no temporal series is bound.

    Raises:
        RuntimeError: temporal series are bound without their configuration, or neither the
            deployment nor the runtime can provide Forseti's projection store.
    """

    provider = container.temporal_causal_evidence_provider
    if provider is None:
        return None
    projection = container.causal_hypothesis_projection
    if projection is None and ontology_instance_store is not None:
        projection = CausalHypothesisProjector(store=ontology_instance_store)
    if container.temporal_causality_config is None or projection is None:
        raise RuntimeError("temporal causal evidence requires config and Forseti-owned projection")
    receipt_verifier = container.causal_intervention_receipt_verifier
    if receipt_verifier is None:
        receipt_verifier = StateStoreCausalInterventionReceiptVerifier(audit_store)
    return CausalRuntimeCoordinator(
        evidence_provider=provider,
        analyzer=TemporalCausalityAnalyzer(container.temporal_causality_config),
        projector=projection,
        method_version=method_version,
        intervention_receipt_verifier=receipt_verifier,
        decision_evidence_provider=container.decision_evidence_admission_provider,
    )


__all__ = ["build_causal_runtime_coordinator"]
