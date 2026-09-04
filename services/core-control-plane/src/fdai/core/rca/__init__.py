"""Root-cause analysis - a first-class, grounded tier output.

See [observability](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
section 4. RCA answers "why" (a hypothesis with citations); the risk
gate and verifier remain authoritative over "execute". T0 is
deterministic (from the matched rule); T2 reasoning plugs in behind the
:class:`RcaReasoner` seam. Every hypothesis passes the grounding gate -
ungrounded abstains to HIL.
"""

from __future__ import annotations

from fdai.core.rca.causal_chain import (
    CausalChain,
    CausalChainAnalyzer,
    CausalChainConfig,
    CausalHop,
    Relationship,
    chain_to_hypothesis,
)
from fdai.core.rca.contract import (
    CauseDomain,
    Citation,
    CitationKind,
    RcaCausalChain,
    RcaCausalHop,
    RcaOutcome,
    RcaResult,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.core.rca.coordinator import RcaCoordinator
from fdai.core.rca.deployment_member_source import DeploymentHistoryMemberSource
from fdai.core.rca.discrimination import (
    DISCRIMINATION_METHOD_VERSION,
    DISCRIMINATION_SCHEMA_VERSION,
    CandidateRejection,
    CandidateRejectionReason,
    DiscriminatingObservationCandidate,
    DiscriminationDisposition,
    DiscriminationHoldReason,
    ExpectedObservationOutcome,
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
    HypothesisOutcomePrediction,
    build_discriminating_observation_candidate,
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)
from fdai.core.rca.discrimination_shadow import (
    ChallengerComparisonOutcome,
    DiscriminationSelector,
    DiscriminationShadowComparison,
    ShadowComparisonDisposition,
    ShadowComparisonHoldReason,
    run_discrimination_shadow,
)
from fdai.core.rca.evidence import TelemetryEvidenceGatherer
from fdai.core.rca.grounding import enforce_grounding
from fdai.core.rca.hypothesis import (
    CAUSAL_CLOSURE_EVIDENCE_PURPOSE,
    CausalActionMode,
    CausalClosure,
    CausalEvidenceAssessment,
    CausalHypothesisRecord,
    CausalHypothesisStatus,
    build_causal_hypothesis,
    causal_action_mode,
    causal_closure_evidence_digest,
    causal_closure_rejection_reasons,
    causal_closure_scope_digest,
    close_causal_hypothesis,
)
from fdai.core.rca.incident_graph import (
    CausalIncidentGraph,
    CausalIncidentGraphMaterializer,
    IncidentGraphBounds,
)
from fdai.core.rca.knowledge_evidence import KnowledgeEvidenceGatherer
from fdai.core.rca.llm import LlmRcaReasoner, RcaModel, parse_rca_response
from fdai.core.rca.member_source import (
    IncidentMemberSource,
    IncidentRcaContext,
    IncidentRcaContextSource,
    NoopIncidentMemberSource,
)
from fdai.core.rca.projection import CausalHypothesisProjector
from fdai.core.rca.reasoner import RcaReasoner
from fdai.core.rca.runtime import (
    CausalClosureObservation,
    CausalHypothesisProjection,
    CausalInterventionReceiptVerifier,
    CausalRuntimeCoordinator,
    CausalRuntimeOutcome,
    CausalRuntimeResult,
    TemporalCausalEvidence,
    TemporalCausalEvidenceProvider,
)
from fdai.core.rca.t0 import t0_root_cause
from fdai.core.rca.t1 import CorrelatedEvent, t1_causal_chain
from fdai.core.rca.temporal_causality import (
    TemporalCausalClaim,
    TemporalCausalityAnalyzer,
    TemporalCausalityConfig,
    TemporalSeries,
)

__all__ = [
    "CAUSAL_CLOSURE_EVIDENCE_PURPOSE",
    "CausalActionMode",
    "CausalChain",
    "CausalChainAnalyzer",
    "CausalChainConfig",
    "CausalHop",
    "CausalClosure",
    "CausalClosureObservation",
    "CausalEvidenceAssessment",
    "CausalHypothesisRecord",
    "CausalHypothesisProjector",
    "CausalHypothesisProjection",
    "CausalInterventionReceiptVerifier",
    "CausalHypothesisStatus",
    "CausalIncidentGraph",
    "CausalIncidentGraphMaterializer",
    "CausalRuntimeCoordinator",
    "CausalRuntimeOutcome",
    "CausalRuntimeResult",
    "CandidateRejection",
    "CandidateRejectionReason",
    "ChallengerComparisonOutcome",
    "CauseDomain",
    "Citation",
    "CitationKind",
    "CorrelatedEvent",
    "DeploymentHistoryMemberSource",
    "DISCRIMINATION_METHOD_VERSION",
    "DISCRIMINATION_SCHEMA_VERSION",
    "DiscriminatingObservationCandidate",
    "DiscriminationSelector",
    "DiscriminationShadowComparison",
    "DiscriminationDisposition",
    "DiscriminationHoldReason",
    "ExpectedObservationOutcome",
    "HypothesisDiscriminationFrame",
    "HypothesisDiscriminationSelection",
    "HypothesisOutcomePrediction",
    "IncidentMemberSource",
    "IncidentRcaContext",
    "IncidentRcaContextSource",
    "IncidentGraphBounds",
    "LlmRcaReasoner",
    "KnowledgeEvidenceGatherer",
    "NoopIncidentMemberSource",
    "RcaCoordinator",
    "RcaCausalChain",
    "RcaCausalHop",
    "RcaModel",
    "RcaOutcome",
    "RcaReasoner",
    "RcaResult",
    "RcaTier",
    "Relationship",
    "RootCauseHypothesis",
    "ShadowComparisonDisposition",
    "ShadowComparisonHoldReason",
    "TelemetryEvidenceGatherer",
    "TemporalCausalClaim",
    "TemporalCausalEvidence",
    "TemporalCausalEvidenceProvider",
    "TemporalCausalityAnalyzer",
    "TemporalCausalityConfig",
    "TemporalSeries",
    "chain_to_hypothesis",
    "build_causal_hypothesis",
    "build_discriminating_observation_candidate",
    "build_hypothesis_discrimination_frame",
    "causal_action_mode",
    "causal_closure_evidence_digest",
    "causal_closure_rejection_reasons",
    "causal_closure_scope_digest",
    "close_causal_hypothesis",
    "enforce_grounding",
    "parse_rca_response",
    "select_discriminating_observation",
    "run_discrimination_shadow",
    "t0_root_cause",
    "t1_causal_chain",
]
