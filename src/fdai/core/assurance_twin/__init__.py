"""Assurance Twin - queryable read-only projection over the estate.

Implements the [assurance-twin.md](../../../../docs/roadmap/operations/assurance-twin.md)
subsystem: a text-to-query surface + ambient PR review + whole-graph
what-if simulation, all backed by the shared
:class:`~fdai.shared.providers.projection.ScratchProjection`
primitive (R4).

Wave scope:

- **Groundwork (this module)**: package marker, in-memory
  :class:`InMemoryProjection` primitive that satisfies the Protocol so
  Twin + Preflight callers have something to bind at composition
  time. The subsystem is intentionally light-weight: no adapter, no
  cloud SDK, no LLM.
- **P2**: text-to-query compiler + verifier (Twin's `query.py`),
  grounded answer rendering, discovery-loop hook.
- **P3**: ambient per-change review posting Checks-API annotations,
  whole-graph what-if for the three verticals, and the
  :class:`PostureAssessmentReport` panel.

The subsystem holds no privileged identity and never mutates.
"""

from __future__ import annotations

from fdai.core.assurance_twin.effect_model import (
    BranchPrediction,
    CausalEvidenceGrade,
    ChallengerUpdate,
    DynamicSimulationResult,
    EffectModel,
    EffectModelStatus,
    SimulationBranch,
    SimulationSnapshot,
    simulate_effect_branches,
    update_challenger,
)
from fdai.core.assurance_twin.fidelity import (
    FidelityStat,
    SimulationFidelityLedger,
)
from fdai.core.assurance_twin.graph_closure import (
    GraphClosureReport,
    GraphDynamicClosureCoordinator,
    GraphDynamicClosureRunner,
    GraphTrajectoryOutcomeSource,
    MetricGraphTrajectoryOutcomeSource,
    TrajectoryClosureCommand,
)
from fdai.core.assurance_twin.graph_effect import (
    EffectInteractionTerm,
    GraphDynamicSimulationResult,
    GraphEffectModel,
    GraphIntervention,
    GraphTopologyEdge,
    simulate_graph_effects,
)
from fdai.core.assurance_twin.graph_learning import (
    GraphChallengerUpdate,
    GraphModelLearningObservation,
    update_graph_challenger,
)
from fdai.core.assurance_twin.graph_model_registry import (
    GraphRegistryUpdate,
    StateStoreGraphEffectModelRegistry,
)
from fdai.core.assurance_twin.graph_runtime import (
    GraphDynamicRuntimeCoordinator,
    GraphDynamicRuntimeResult,
    GraphDynamicSimulationRequest,
    GraphDynamicSimulationRequestProvider,
    GraphEffectModelCausalEvidenceVerifier,
    GraphEffectModelReader,
)
from fdai.core.assurance_twin.model_registry import (
    RegistryUpdate,
    StateStoreEffectModelRegistry,
)
from fdai.core.assurance_twin.projection import (
    InMemoryProjection,
    build_baseline_projection,
)
from fdai.core.assurance_twin.query import (
    AbstainCode,
    AbstainResult,
    CompiledQuery,
    DeterministicPatternCompiler,
    NlQueryCompiler,
    Predicate,
    PredicateOp,
    QueryKind,
    QueryResult,
    QueryRow,
    QueryVerificationError,
    QueryVerifier,
    TypedQuery,
    execute_query,
)
from fdai.core.assurance_twin.report import (
    PostureAssessmentReport,
    PostureVerdict,
    build_posture_assessment_report,
)
from fdai.core.assurance_twin.review import (
    ReviewOutcome,
    ReviewResult,
    publish_review,
)
from fdai.core.assurance_twin.runtime import (
    DynamicRuntimeCoordinator,
    DynamicRuntimeResult,
    DynamicSimulationRequest,
    DynamicSimulationRequestProvider,
    EffectModelCausalEvidenceVerifier,
    EffectModelReader,
)
from fdai.core.assurance_twin.state_trajectory import (
    DynamicInvariant,
    InvariantOperator,
    InvariantResult,
    InvariantStatus,
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
    TrajectoryOutcome,
    TrajectoryOutcomeStatus,
    close_trajectory_outcome,
    evaluate_dynamic_invariants,
)
from fdai.core.assurance_twin.trajectory_ledger import (
    OpenTrajectoryEpisode,
    StateStoreTrajectoryEpisodeLedger,
    TrajectoryClosure,
    TrajectoryEpisodeConflictError,
)

__all__ = [
    "AbstainCode",
    "AbstainResult",
    "BranchPrediction",
    "CausalEvidenceGrade",
    "ChallengerUpdate",
    "CompiledQuery",
    "DeterministicPatternCompiler",
    "DynamicSimulationResult",
    "DynamicRuntimeCoordinator",
    "DynamicRuntimeResult",
    "DynamicSimulationRequest",
    "DynamicSimulationRequestProvider",
    "DynamicInvariant",
    "EffectModel",
    "EffectModelStatus",
    "EffectModelReader",
    "EffectModelCausalEvidenceVerifier",
    "EffectInteractionTerm",
    "GraphDynamicSimulationResult",
    "GraphDynamicRuntimeCoordinator",
    "GraphDynamicRuntimeResult",
    "GraphDynamicSimulationRequest",
    "GraphDynamicSimulationRequestProvider",
    "GraphChallengerUpdate",
    "GraphClosureReport",
    "GraphDynamicClosureCoordinator",
    "GraphDynamicClosureRunner",
    "GraphEffectModel",
    "GraphEffectModelCausalEvidenceVerifier",
    "GraphEffectModelReader",
    "GraphModelLearningObservation",
    "GraphRegistryUpdate",
    "GraphIntervention",
    "GraphTopologyEdge",
    "GraphTrajectoryOutcomeSource",
    "MetricGraphTrajectoryOutcomeSource",
    "InMemoryProjection",
    "InvariantOperator",
    "InvariantResult",
    "InvariantStatus",
    "NlQueryCompiler",
    "OperationalStateTrajectory",
    "OpenTrajectoryEpisode",
    "PostureAssessmentReport",
    "PostureVerdict",
    "Predicate",
    "PredicateOp",
    "QueryKind",
    "QueryResult",
    "QueryRow",
    "QueryVerificationError",
    "QueryVerifier",
    "ReviewOutcome",
    "ReviewResult",
    "RegistryUpdate",
    "FidelityStat",
    "SimulationFidelityLedger",
    "SimulationBranch",
    "SimulationSnapshot",
    "StateStoreEffectModelRegistry",
    "StateStoreGraphEffectModelRegistry",
    "StateStoreTrajectoryEpisodeLedger",
    "StateSlice",
    "TrajectoryKind",
    "TrajectoryClosure",
    "TrajectoryClosureCommand",
    "TrajectoryEpisodeConflictError",
    "TrajectoryOutcome",
    "TrajectoryOutcomeStatus",
    "TypedQuery",
    "build_baseline_projection",
    "build_posture_assessment_report",
    "close_trajectory_outcome",
    "execute_query",
    "evaluate_dynamic_invariants",
    "publish_review",
    "simulate_effect_branches",
    "simulate_graph_effects",
    "update_challenger",
    "update_graph_challenger",
]
