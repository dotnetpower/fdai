"""Runtime composition for strict Assurance Twin semantic query compilation."""

from __future__ import annotations

from collections.abc import Iterable

from fdai.composition import Container
from fdai.core.assurance_twin import (
    AssuranceTwinSemanticQueryCoordinator,
    DeterministicPatternCompiler,
    QueryVerifier,
)
from fdai.core.assurance_twin.proposal_effects import (
    ReviewedActionTypeEffect,
    ReviewedEffectCatalog,
)
from fdai.delivery.assurance_twin_remediation_bridge import (
    AssuranceTwinRemediationProposalBridge,
    InMemoryRiskGatedRemediationSink,
    RiskGatedRemediationSink,
    TypedPipelineWhatIfProducer,
    TypedProposalIntakeTarget,
    build_reviewed_action_effect_catalog,
)
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry


def build_assurance_twin_semantic_query(
    container: Container,
    *,
    resource_types: ResourceTypeRegistry,
) -> AssuranceTwinSemanticQueryCoordinator:
    """Bind injected compiler/discovery seams with an explicit unavailable default."""

    compiler = container.assurance_twin_query_compiler or DeterministicPatternCompiler(
        resource_types
    )
    revision = (
        type(compiler).__name__
        if container.assurance_twin_query_compiler is not None
        else "unavailable-v1"
    )
    return AssuranceTwinSemanticQueryCoordinator(
        compiler=compiler,
        verifier=QueryVerifier(resource_types, require_compiler_evidence=True),
        compiler_revision=revision,
        discovery_sink=container.assurance_twin_discovery_sink,
    )


def build_typed_pipeline_what_if_producer(
    intake: TypedProposalIntakeTarget,
    *,
    effects: ReviewedEffectCatalog | None = None,
    producer_id: str = "typed-pipeline-what-if-producer",
) -> TypedPipelineWhatIfProducer:
    """Build a TypedPipelineWhatIfProducer backed by the reviewed ActionType effect catalog."""
    return TypedPipelineWhatIfProducer(
        intake=intake,
        effects=effects or build_reviewed_action_effect_catalog(),
        producer_id=producer_id,
    )


def build_assurance_twin_remediation_bridge(
    container: Container,
    *,
    action_sink: RiskGatedRemediationSink | None = None,
    what_if_producer: TypedPipelineWhatIfProducer | None = None,
    extra_effects: Iterable[ReviewedActionTypeEffect] = (),
) -> AssuranceTwinRemediationProposalBridge:
    """Bind the Assurance Twin remediation bridge in shadow mode with zero execution authority."""
    return AssuranceTwinRemediationProposalBridge(
        effects=build_reviewed_action_effect_catalog(extra_effects),
        action_sink=action_sink or InMemoryRiskGatedRemediationSink(),
        discovery_sink=container.assurance_twin_discovery_sink,
        what_if_producer=what_if_producer,
    )


__all__ = [
    "AssuranceTwinRemediationProposalBridge",
    "TypedPipelineWhatIfProducer",
    "build_assurance_twin_remediation_bridge",
    "build_assurance_twin_semantic_query",
    "build_reviewed_action_effect_catalog",
    "build_typed_pipeline_what_if_producer",
]
