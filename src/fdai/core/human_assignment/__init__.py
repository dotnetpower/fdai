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
    "AssignmentConflictError",
    "AssignmentCoverageError",
    "AssignmentIntent",
    "AssignmentModelError",
    "AssignmentOwnershipError",
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
    "ProviderSubject",
    "ReviewDecision",
    "ReviewReceipt",
    "StaleAssignmentRevisionError",
    "TransitionIntent",
    "approval_quorum_satisfied",
    "required_review_quorum",
    "render_assignment_ownership_yaml",
    "validate_transition",
]
