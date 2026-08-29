"""A3-E standing-authorization records and their deterministic evaluator.

Nothing in this package is wired into a decision path. See
[escalation-and-standing-authority.md](../../../../../../docs/roadmap/decisioning/escalation-and-standing-authority.md).
"""

from fdai.core.standing_authority.evaluator import (
    AuthorizationRequest,
    AutonomyClass,
    Eligibility,
    StandingAuthorizationDecision,
    evaluate_standing_authorization,
)
from fdai.core.standing_authority.fence import (
    LifecycleFenceReason,
    LifecycleFenceResult,
    StandingAuthorizationFenceGuard,
)
from fdai.core.standing_authority.lifecycle import (
    AuthenticatedAuthorizationCommand,
    AuthorizationCommandKind,
    AuthorizationLifecycleCommand,
    AuthorizationLifecycleError,
    AuthorizationLifecycleWriteResult,
    AuthorizationProofBindings,
    AuthorizationRevision,
    AuthorizationSnapshot,
    AuthorizationSnapshotStatus,
    AuthorizationTransition,
    AuthorizationWriteStatus,
    LifecycleFence,
    StandingAuthorizationLifecycleWriter,
    authorization_revision_id,
    fence_matches,
    plan_lifecycle_transition,
    replay_lifecycle,
)
from fdai.core.standing_authority.record import (
    StandingAuthorization,
    StandingAuthorizationError,
    load_schema,
)

__all__ = [
    "AuthorizationRequest",
    "AuthenticatedAuthorizationCommand",
    "AuthorizationCommandKind",
    "AuthorizationLifecycleCommand",
    "AuthorizationLifecycleError",
    "AuthorizationLifecycleWriteResult",
    "AuthorizationProofBindings",
    "AuthorizationRevision",
    "AuthorizationSnapshot",
    "AuthorizationSnapshotStatus",
    "AuthorizationTransition",
    "AuthorizationWriteStatus",
    "AutonomyClass",
    "Eligibility",
    "LifecycleFence",
    "LifecycleFenceReason",
    "LifecycleFenceResult",
    "StandingAuthorization",
    "StandingAuthorizationDecision",
    "StandingAuthorizationError",
    "StandingAuthorizationFenceGuard",
    "StandingAuthorizationLifecycleWriter",
    "authorization_revision_id",
    "evaluate_standing_authorization",
    "fence_matches",
    "load_schema",
    "plan_lifecycle_transition",
    "replay_lifecycle",
]
