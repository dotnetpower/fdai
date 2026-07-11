"""Root-cause analysis - a first-class, grounded tier output.

See [observability-and-detection.md](../../../../docs/roadmap/observability-and-detection.md)
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
    Citation,
    CitationKind,
    RcaOutcome,
    RcaResult,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.core.rca.coordinator import RcaCoordinator
from fdai.core.rca.deployment_member_source import DeploymentHistoryMemberSource
from fdai.core.rca.evidence import TelemetryEvidenceGatherer
from fdai.core.rca.grounding import enforce_grounding
from fdai.core.rca.llm import LlmRcaReasoner, RcaModel, parse_rca_response
from fdai.core.rca.member_source import IncidentMemberSource, NoopIncidentMemberSource
from fdai.core.rca.reasoner import RcaReasoner
from fdai.core.rca.t0 import t0_root_cause
from fdai.core.rca.t1 import CorrelatedEvent, t1_causal_chain

__all__ = [
    "CausalChain",
    "CausalChainAnalyzer",
    "CausalChainConfig",
    "CausalHop",
    "Citation",
    "CitationKind",
    "CorrelatedEvent",
    "DeploymentHistoryMemberSource",
    "IncidentMemberSource",
    "LlmRcaReasoner",
    "NoopIncidentMemberSource",
    "RcaCoordinator",
    "RcaModel",
    "RcaOutcome",
    "RcaReasoner",
    "RcaResult",
    "RcaTier",
    "Relationship",
    "RootCauseHypothesis",
    "TelemetryEvidenceGatherer",
    "chain_to_hypothesis",
    "enforce_grounding",
    "parse_rca_response",
    "t0_root_cause",
    "t1_causal_chain",
]
