"""Exact-plan validation for execution access-grant proposals."""

from __future__ import annotations

from datetime import timedelta

from fdai.shared.providers.execution_authorization import (
    ExecutionAccessGrantPlanRequest,
    ExecutionAccessGrantProposal,
)


def validate_grant_proposal(
    request: ExecutionAccessGrantPlanRequest,
    proposal: ExecutionAccessGrantProposal,
) -> None:
    expected = (
        (proposal.authorization_decision_digest, request.authorization_decision_digest),
        (proposal.idempotency_key, request.original_request.idempotency_key),
        (proposal.original_action_id, request.original_request.action_id),
        (proposal.requirement_id, request.requirement_id),
        (proposal.capability_id, request.capability_id),
        (proposal.execution_profile, request.execution_profile),
        (proposal.executor_identity_ref, request.executor_identity_ref),
        (proposal.scope_ref, request.scope_ref),
        (proposal.mapping_digest, request.mapping_digest),
        (proposal.requester_ref, request.requester_ref),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise ValueError("grant proposal changed an exact-plan field")
    if proposal.grant_mode not in request.allowed_grant_modes:
        raise ValueError("grant proposal mode is outside authorization constraints")
    if proposal.quorum < request.quorum or not request.approver_roles <= proposal.approver_roles:
        raise ValueError("grant proposal weakened approval constraints")
    if proposal.requested_at != request.requested_at:
        raise ValueError("grant proposal changed the request timestamp")
    if proposal.expires_at > request.requested_at + timedelta(seconds=request.max_duration_seconds):
        raise ValueError("grant proposal exceeds maximum duration")


__all__ = ["validate_grant_proposal"]
