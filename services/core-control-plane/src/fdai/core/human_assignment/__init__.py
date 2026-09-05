"""Composite human access and agent-duty assignment lifecycle."""

from fdai.core.human_assignment.access_apply import (
    HumanAccessApplyCoordinator,
    HumanAccessExecution,
    HumanAccessExecutionOutcome,
)
from fdai.core.human_assignment.audit import AssignmentAuditKind
from fdai.core.human_assignment.coverage import (
    AssignmentCoverageError,
    approval_quorum_satisfied,
    required_review_quorum,
)
from fdai.core.human_assignment.errors import (
    AssignmentConflictError,
    AssignmentPermissionError,
    AssignmentServiceError,
)
from fdai.core.human_assignment.fatigue import HandoverFatiguePolicy
from fdai.core.human_assignment.goals import (
    GoalEvidence,
    HandoverGoal,
    HandoverGoalService,
    HandoverGoalState,
    HandoverInvitation,
)
from fdai.core.human_assignment.knowledge_handover import (
    HandoverKnowledgeAccessContext,
    HandoverKnowledgeClaim,
    HandoverKnowledgeRetrieval,
    publish_knowledge_conflict,
)
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentModelError,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    ProviderSubject,
    ReviewDecision,
    ReviewReceipt,
)
from fdai.core.human_assignment.ownership import (
    AssignmentOwnershipError,
    render_assignment_ownership_yaml,
)
from fdai.core.human_assignment.ownership_coordination import (
    AssignmentOwnershipCoordinator,
    OwnershipProposal,
    VerifiedOwnershipMerge,
)
from fdai.core.human_assignment.production_controls import (
    AssignmentCapabilityStatus,
    AssignmentReconciler,
    AssignmentReconciliationItem,
    assignment_capability_status,
)
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.human_assignment.transitions import (
    ALLOWED_TRANSITIONS,
    AssignmentTransitionError,
    StaleAssignmentRevisionError,
    TransitionIntent,
    validate_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AssignmentAuditKind",
    "AssignmentCase",
    "AssignmentCaseService",
    "AssignmentCapabilityStatus",
    "AssignmentReconciler",
    "AssignmentReconciliationItem",
    "AssignmentConflictError",
    "AssignmentCoverageError",
    "AssignmentIntent",
    "AssignmentModelError",
    "AssignmentOwnershipError",
    "AssignmentOwnershipCoordinator",
    "AssignmentPermissionError",
    "AssignmentServiceError",
    "AssignmentState",
    "AssignmentTransitionError",
    "DutyBinding",
    "EffectKind",
    "EffectReceipt",
    "HumanAccessApplyCoordinator",
    "HumanAccessExecution",
    "HumanAccessExecutionOutcome",
    "GoalEvidence",
    "HandoverFatiguePolicy",
    "HandoverGoal",
    "HandoverGoalService",
    "HandoverGoalState",
    "HandoverInvitation",
    "HandoverKnowledgeAccessContext",
    "HandoverKnowledgeClaim",
    "HandoverKnowledgeRetrieval",
    "ProviderSubject",
    "ReviewDecision",
    "ReviewReceipt",
    "StaleAssignmentRevisionError",
    "TransitionIntent",
    "approval_quorum_satisfied",
    "required_review_quorum",
    "render_assignment_ownership_yaml",
    "publish_knowledge_conflict",
    "OwnershipProposal",
    "VerifiedOwnershipMerge",
    "assignment_capability_status",
    "validate_transition",
]
