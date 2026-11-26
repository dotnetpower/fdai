"""Inert A3-E promotion-candidate lifecycle (shadow-only, no execution authority).

``LEASE_CONTRACT_VERSION`` pins the exact #621 lease. ``ActionPromotionRegistry`` is
never imported or mutated. All records carry ``execution_authority=False`` and
``promotion_authority=False``. Fail-closed: self-review, silence, duplicate/conflicting
review, agent/executor identity, missing evidence, stale fence, provider-ineligible
ActionType, and explicit revocation all terminate deterministically. The ineligible
ActionType set is derived from ``provider_eligibility``; no caller declares it.
Two-phase audit: immutable intent digest captured before mutation; result committed in
the same boundary. Append-only hash-chained history with monotonic sequence.

Re-exports all public names from the focused sub-modules:
  - ``promotion_candidate_models``: immutable record types and persistence protocol.
  - ``promotion_candidate_ops``: builder, planners, and replay function.
"""

from fdai.core.standing_authority.promotion_candidate_models import (
    CANDIDATE_QUORUM,
    LEASE_CONTRACT_VERSION,
    CandidateReviewRecord,
    CandidateRevocationRecord,
    CandidateSnapshot,
    CandidateStatus,
    CandidateTransition,
    CandidateTransitionKind,
    DenialReason,
    PromotionCandidateRecord,
    PromotionCandidateStore,
    PromotionCandidateWriteResult,
    ReviewDecision,
    TerminalDenialRecord,
)
from fdai.core.standing_authority.promotion_candidate_ops import (
    build_candidate_record,
    plan_create_transition,
    plan_external_denial,
    plan_review_transition,
    replay_candidate,
)

__all__ = [
    "CANDIDATE_QUORUM",
    "LEASE_CONTRACT_VERSION",
    "CandidateReviewRecord",
    "CandidateRevocationRecord",
    "CandidateSnapshot",
    "CandidateStatus",
    "CandidateTransition",
    "CandidateTransitionKind",
    "DenialReason",
    "PromotionCandidateRecord",
    "PromotionCandidateStore",
    "PromotionCandidateWriteResult",
    "ReviewDecision",
    "TerminalDenialRecord",
    "build_candidate_record",
    "plan_create_transition",
    "plan_external_denial",
    "plan_review_transition",
    "replay_candidate",
]
