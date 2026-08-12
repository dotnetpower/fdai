"""Azure operational-learning evidence composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from fdai.core.assurance_twin import (
    EffectModelCausalEvidenceVerifier,
    EffectModelReader,
    GraphDynamicSimulationRequestProvider,
    GraphEffectModelCausalEvidenceVerifier,
    GraphEffectModelReader,
)
from fdai.core.rca import TemporalCausalityConfig
from fdai.delivery.azure.graph_dynamic_evidence import (
    AzureGraphDynamicSimulationRequestProvider,
    AzureGraphInterventionPolicy,
    AzureGraphInventoryEvidenceReader,
    AzureGraphMetricEvidenceReader,
    AzureGraphOperationalContextSource,
    AzureGraphTopologyEvidenceReader,
)
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
from fdai.shared.contracts.models import OntologyActionType

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
    graph_contexts: AzureGraphOperationalContextSource | None = None,
    graph_topology: AzureGraphTopologyEvidenceReader | None = None,
    graph_inventory: AzureGraphInventoryEvidenceReader | None = None,
    graph_metrics: AzureGraphMetricEvidenceReader | None = None,
    graph_action_types: Mapping[str, OntologyActionType] | None = None,
    graph_policies: Mapping[str, AzureGraphInterventionPolicy] | None = None,
    graph_effect_models: GraphEffectModelReader | None = None,
    graph_effect_model_causal_evidence: GraphEffectModelCausalEvidenceVerifier | None = None,
) -> Container:
    """Bind read-only Azure evidence, including graph Dynamic when complete.

    Graph Dynamic remains explicitly unavailable when every optional prerequisite is absent.
    Partial raw prerequisites, mixed prebuilt/raw provider input, or an incomplete verified
    model pair fail during composition rather than producing a degraded runtime binding.
    """
    raw_graph_prerequisites = (
        graph_contexts,
        graph_topology,
        graph_inventory,
        graph_metrics,
        graph_action_types,
        graph_policies,
    )
    any_raw_graph_prerequisite = any(item is not None for item in raw_graph_prerequisites)
    if graph_request_provider is not None and any_raw_graph_prerequisite:
        raise ValueError(
            "prebuilt graph Dynamic provider cannot be combined with raw prerequisites"
        )
    if any_raw_graph_prerequisite and not all(item is not None for item in raw_graph_prerequisites):
        raise ValueError("graph Dynamic prerequisites MUST be bound together")
    if any(item is not None for item in (graph_effect_models, graph_effect_model_causal_evidence)):
        if graph_effect_models is None or graph_effect_model_causal_evidence is None:
            raise ValueError("graph Dynamic verified model prerequisites MUST be bound together")
        if graph_request_provider is None and not any_raw_graph_prerequisite:
            raise ValueError("graph Dynamic models require a request provider")
    if any_raw_graph_prerequisite:
        graph_request_provider = AzureGraphDynamicSimulationRequestProvider(
            contexts=cast(AzureGraphOperationalContextSource, graph_contexts),
            topology=cast(AzureGraphTopologyEvidenceReader, graph_topology),
            inventory=cast(AzureGraphInventoryEvidenceReader, graph_inventory),
            metrics=cast(AzureGraphMetricEvidenceReader, graph_metrics),
            action_types=cast(Mapping[str, OntologyActionType], graph_action_types),
            policies=cast(Mapping[str, AzureGraphInterventionPolicy], graph_policies),
        )
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
