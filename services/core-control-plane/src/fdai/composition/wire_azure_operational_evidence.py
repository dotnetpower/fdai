"""Azure operational-learning evidence composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from fdai.core.assurance_twin import (
    EffectModelCausalEvidenceVerifier,
    EffectModelReader,
    GraphDynamicSimulationRequestProvider,
    GraphEffectModelCausalEvidenceVerifier,
    GraphEffectModelReader,
)
from fdai.core.rca import TemporalCausalityConfig
from fdai.delivery.azure.operational_evidence import (
    AzureBranchEstimator,
    AzureCurrentReuseVerifier,
    AzureDynamicPolicy,
    AzureDynamicSimulationRequestProvider,
    AzureOperationalSnapshotSource,
    AzureReuseSafetyEvaluator,
    AzureTemporalCausalEvidenceProvider,
    AzureTemporalPolicy,
)

from ._helpers import Container


def bind_azure_operational_evidence(
    container: Container,
    *,
    snapshots: AzureOperationalSnapshotSource,
    safety: AzureReuseSafetyEvaluator,
    temporal_policies: Mapping[str, AzureTemporalPolicy],
    temporal_config: TemporalCausalityConfig,
    branch_estimator: AzureBranchEstimator,
    dynamic_policies: Mapping[str, AzureDynamicPolicy],
    effect_models: EffectModelReader,
    effect_model_causal_evidence: EffectModelCausalEvidenceVerifier,
    graph_request_provider: GraphDynamicSimulationRequestProvider | None = None,
    graph_effect_models: GraphEffectModelReader | None = None,
    graph_effect_model_causal_evidence: GraphEffectModelCausalEvidenceVerifier | None = None,
) -> Container:
    """Return a container with read-only Azure learning evidence bound."""
    return replace(
        container,
        current_reuse_verifier=AzureCurrentReuseVerifier(
            snapshots=snapshots,
            safety=safety,
        ),
        temporal_causal_evidence_provider=AzureTemporalCausalEvidenceProvider(
            snapshots=snapshots,
            metrics=container.metric_provider,
            policies=temporal_policies,
        ),
        temporal_causality_config=temporal_config,
        dynamic_simulation_request_provider=AzureDynamicSimulationRequestProvider(
            snapshots=snapshots,
            estimator=branch_estimator,
            policies=dynamic_policies,
        ),
        effect_model_reader=effect_models,
        effect_model_causal_evidence_verifier=effect_model_causal_evidence,
        graph_dynamic_simulation_request_provider=graph_request_provider,
        graph_effect_model_reader=graph_effect_models,
        graph_effect_model_causal_evidence_verifier=graph_effect_model_causal_evidence,
    )


__all__ = ["bind_azure_operational_evidence"]
