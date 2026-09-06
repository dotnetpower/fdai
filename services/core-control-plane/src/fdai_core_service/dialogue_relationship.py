"""Admit expiring Operator-owned relationship context without changing authority."""

from __future__ import annotations

import logging
from datetime import datetime

from fdai.core.conversation.adaptive_prompt import (
    ConversationRelationshipKind,
    VerifiedConversationRelationship,
)
from fdai_service_contracts import OperatorPrincipalKind, SemanticTurnRequest

_LOGGER = logging.getLogger(__name__)


def runtime_relationship(request: SemanticTurnRequest, *, now: datetime) -> dict[str, object]:
    """Recheck the transported observation against the current request and clock."""
    proof = request.relationship_proof
    if proof is None:
        return _unknown(
            request,
            request.relationship_unknown_reason or "relationship_proof_unavailable",
        )
    if (
        now.tzinfo is None
        or now.utcoffset() is None
        or request.principal.principal_kind is not OperatorPrincipalKind.HUMAN
        or proof.principal_id != request.principal.subject_id
        or proof.target_agent != request.target_agent
        or not proof.verified_at <= now < proof.expires_at
    ):
        return _unknown(request, "proof_stale_or_mismatched")
    try:
        relationship = VerifiedConversationRelationship(
            kind=ConversationRelationshipKind(proof.kind),
            target_agent=proof.target_agent,
            source_revision=proof.source_revision,
            verified_at=proof.verified_at,
            expires_at=proof.expires_at,
        )
    except (TypeError, ValueError):
        return _unknown(request, "proof_revision_unsupported")
    return {
        "verified_relationship": relationship,
        "relationship_proof": proof,
    }


def _unknown(request: SemanticTurnRequest, reason: str) -> dict[str, object]:
    _LOGGER.info(
        "semantic_relationship_unknown",
        extra={"target_agent": request.target_agent, "reason": reason},
    )
    return {
        "relationship_status": "unknown",
        "relationship_unknown_reason": reason,
    }
