"""Operational handoff and deterministic startup readiness contracts."""

from __future__ import annotations

from fdai.core.readiness.checklist import (
    ChecklistControlResult,
    ChecklistControlStatus,
    evaluate_best_practices,
)
from fdai.core.readiness.coordinator import compose_readiness_report
from fdai.core.readiness.decision_evidence import (
    DecisionEvidenceReadinessGate,
    DecisionEvidenceReadinessReason,
    DecisionEvidenceReadinessResult,
)
from fdai.core.readiness.detection import (
    DETECTION_READINESS_STATE_PREFIX,
    DetectionObservationStatus,
    DetectionReadinessDecision,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    DetectionReadinessSnapshot,
    detection_readiness_state_key,
    reduce_detection_readiness,
)
from fdai.core.readiness.discovery_activation import (
    DISCOVERY_ACTIVATION_STATE_KEY,
    CollectorRunEvidence,
    DiscoveryActivationCoordinator,
    DiscoveryActivationDecision,
    DiscoveryActivationInputs,
    DiscoveryActivationReason,
    DiscoveryActivationReport,
    DiscoveryEvidenceStatus,
    ShadowDecisionEvidence,
    TimedDiscoveryEvidence,
    reduce_discovery_activation,
)
from fdai.core.readiness.models import (
    AuthorityCeiling,
    EvidenceRequirement,
    ModelStartupEvidence,
    ProbeCriticality,
    ProbeStatus,
    ReadinessDecision,
    StartupPhase,
    StartupProbeResult,
    StartupProbeSpec,
    StartupReadinessReport,
)
from fdai.core.readiness.reducer import reduce_startup_readiness
from fdai.core.readiness.remediation import (
    HandoffApproval,
    RemediationProposal,
    SelfApprovalError,
    build_remediation_proposals,
    remediation_idempotency_key,
)
from fdai.core.readiness.report import (
    HandoffVerdict,
    ReadinessFinding,
    ReadinessReport,
)
from fdai.core.readiness.signal import OwnershipTransfer

__all__ = [
    "AuthorityCeiling",
    "ChecklistControlResult",
    "ChecklistControlStatus",
    "DETECTION_READINESS_STATE_PREFIX",
    "DISCOVERY_ACTIVATION_STATE_KEY",
    "CollectorRunEvidence",
    "DetectionObservationStatus",
    "DetectionReadinessDecision",
    "DetectionReadinessDimension",
    "DetectionReadinessObservation",
    "DetectionReadinessSnapshot",
    "DecisionEvidenceReadinessGate",
    "DecisionEvidenceReadinessReason",
    "DecisionEvidenceReadinessResult",
    "DiscoveryActivationCoordinator",
    "DiscoveryActivationDecision",
    "DiscoveryActivationInputs",
    "DiscoveryActivationReason",
    "DiscoveryActivationReport",
    "DiscoveryEvidenceStatus",
    "EvidenceRequirement",
    "HandoffApproval",
    "HandoffVerdict",
    "OwnershipTransfer",
    "ModelStartupEvidence",
    "ProbeCriticality",
    "ProbeStatus",
    "ReadinessFinding",
    "ReadinessReport",
    "ReadinessDecision",
    "RemediationProposal",
    "SelfApprovalError",
    "StartupPhase",
    "StartupProbeResult",
    "StartupProbeSpec",
    "StartupReadinessReport",
    "ShadowDecisionEvidence",
    "TimedDiscoveryEvidence",
    "build_remediation_proposals",
    "compose_readiness_report",
    "detection_readiness_state_key",
    "evaluate_best_practices",
    "reduce_detection_readiness",
    "reduce_discovery_activation",
    "reduce_startup_readiness",
    "remediation_idempotency_key",
]
