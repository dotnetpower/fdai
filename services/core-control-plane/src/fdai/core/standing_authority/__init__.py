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
from fdai.core.standing_authority.record import (
    StandingAuthorization,
    StandingAuthorizationError,
    load_schema,
)

__all__ = [
    "AuthorizationRequest",
    "AutonomyClass",
    "Eligibility",
    "StandingAuthorization",
    "StandingAuthorizationDecision",
    "StandingAuthorizationError",
    "evaluate_standing_authorization",
    "load_schema",
]
