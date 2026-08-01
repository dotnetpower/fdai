"""Composite human access and agent-duty assignment lifecycle."""

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
    "AssignmentPermissionError",
    "AssignmentServiceError",
    "AssignmentState",
    "AssignmentTransitionError",
    "DutyBinding",
    "EffectKind",
    "EffectReceipt",
    "ProviderSubject",
    "ReviewDecision",
    "ReviewReceipt",
    "StaleAssignmentRevisionError",
    "TransitionIntent",
    "approval_quorum_satisfied",
    "required_review_quorum",
    "validate_transition",
]
