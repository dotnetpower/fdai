"""Azure operational evidence composition stays complete or explicitly unavailable."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest
from fdai.composition import Container, bind_azure_operational_evidence
from fdai.core.assurance_twin import (
    EffectModelCausalEvidenceVerifier,
    EffectModelReader,
    GraphEffectModelCausalEvidenceVerifier,
    GraphEffectModelReader,
)
from fdai.core.ontology_platform import (
    ExecutedActionReconciliationArtifactSource,
    ObservationContextVerifier,
    ReconciliationArtifactResolver,
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
    AzureDynamicPolicy,
    AzureOperationalSnapshotSource,
    AzureReuseSafetyEvaluator,
    AzureTemporalPolicy,
)
from fdai.shared.contracts.models import OntologyActionType


def _provider() -> Any:
    return object()


def _bind(
    container: Container,
    *,
    graph_contexts: AzureGraphOperationalContextSource | None = None,
    graph_topology: AzureGraphTopologyEvidenceReader | None = None,
    graph_inventory: AzureGraphInventoryEvidenceReader | None = None,
    graph_metrics: AzureGraphMetricEvidenceReader | None = None,
    graph_action_types: dict[str, OntologyActionType] | None = None,
    graph_policies: dict[str, AzureGraphInterventionPolicy] | None = None,
    graph_effect_models: GraphEffectModelReader | None = None,
    graph_effect_model_causal_evidence: GraphEffectModelCausalEvidenceVerifier | None = None,
) -> Container:
    provider = _provider()
    return bind_azure_operational_evidence(
        container,
        snapshots=cast(AzureOperationalSnapshotSource, provider),
        safety=cast(AzureReuseSafetyEvaluator, provider),
        temporal_policies={
            "event.example": AzureTemporalPolicy(
                cause_metric="cpu",
                effect_metric="latency",
                mechanism="capacity-pressure",
                required_topology_role="implements",
                lookback=timedelta(minutes=5),
            )
        },
        temporal_config=TemporalCausalityConfig(lag_seconds=(30,)),
        branch_estimator=cast(AzureBranchEstimator, provider),
        dynamic_policies={"ops.scale-out": AzureDynamicPolicy(metric="latency")},
        effect_models=cast(EffectModelReader, provider),
        effect_model_causal_evidence=cast(EffectModelCausalEvidenceVerifier, provider),
        graph_contexts=graph_contexts,
        graph_topology=graph_topology,
        graph_inventory=graph_inventory,
        graph_metrics=graph_metrics,
        graph_action_types=graph_action_types,
        graph_policies=graph_policies,
        graph_effect_models=graph_effect_models,
        graph_effect_model_causal_evidence=graph_effect_model_causal_evidence,
    )


def test_absent_graph_prerequisites_leave_explicit_unavailable(container: Container) -> None:
    bound = _bind(container)

    assert bound.graph_dynamic_simulation_request_provider is None
    assert bound.graph_effect_model_reader is None
    assert bound.graph_effect_model_causal_evidence_verifier is None


def test_complete_graph_prerequisites_build_production_provider(container: Container) -> None:
    provider = _provider()
    action_type = cast(OntologyActionType, object())

    bound = _bind(
        container,
        graph_contexts=cast(AzureGraphOperationalContextSource, provider),
        graph_topology=cast(AzureGraphTopologyEvidenceReader, provider),
        graph_inventory=cast(AzureGraphInventoryEvidenceReader, provider),
        graph_metrics=cast(AzureGraphMetricEvidenceReader, provider),
        graph_action_types={"ops.scale-out": action_type},
        graph_policies={
            "ops.scale-out": AzureGraphInterventionPolicy(
                metric="replicas",
                delta=1.0,
                max_abs_delta=2.0,
                horizon=timedelta(minutes=5),
            )
        },
        graph_effect_models=cast(GraphEffectModelReader, provider),
        graph_effect_model_causal_evidence=cast(
            GraphEffectModelCausalEvidenceVerifier,
            provider,
        ),
    )

    assert isinstance(
        bound.graph_dynamic_simulation_request_provider,
        AzureGraphDynamicSimulationRequestProvider,
    )
    assert bound.graph_effect_model_reader is provider


def test_partial_graph_prerequisites_fail_at_composition(container: Container) -> None:
    provider = _provider()

    with pytest.raises(ValueError, match="graph Dynamic prerequisites MUST be bound together"):
        _bind(
            container,
            graph_contexts=cast(AzureGraphOperationalContextSource, provider),
        )


def test_partial_reconciliation_prerequisites_fail_at_container(container: Container) -> None:
    with pytest.raises(
        ValueError,
        match="reconciliation artifact resolver and observation verifier",
    ):
        replace(
            container,
            reconciliation_artifact_resolver=cast(ReconciliationArtifactResolver, object()),
        )

    with pytest.raises(ValueError, match="executed-Action artifact"):
        replace(
            container,
            executed_action_reconciliation_artifact_source=cast(
                ExecutedActionReconciliationArtifactSource,
                object(),
            ),
        )


def test_complete_reconciliation_prerequisites_bind_together(container: Container) -> None:
    provider = object()

    bound = replace(
        container,
        reconciliation_artifact_resolver=cast(ReconciliationArtifactResolver, provider),
        reconciliation_observation_verifier=cast(ObservationContextVerifier, provider),
    )

    assert bound.reconciliation_artifact_resolver is not None
    assert bound.reconciliation_observation_verifier is not None
