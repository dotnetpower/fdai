"""Decode and bind one semantic turn request at the Core service boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fdai.core.conversation.semantic_planning_models import (
    BoundIncident,
    BoundInvestigationContinuation,
    BoundResourceContext,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai_service_contracts import OperatorRole, SemanticTurnRequest

from .contract_codecs import OPERATOR_REQUEST_CONSUMER_V18

_ROLE_ORDER = (
    OperatorRole.READER,
    OperatorRole.CONTRIBUTOR,
    OperatorRole.APPROVER,
    OperatorRole.OWNER,
)
_ROLE_MAP = {
    OperatorRole.READER: Role.READER,
    OperatorRole.CONTRIBUTOR: Role.CONTRIBUTOR,
    OperatorRole.APPROVER: Role.APPROVER,
    OperatorRole.OWNER: Role.OWNER,
}


class SemanticTurnRejectedError(ValueError):
    """Reject one malformed or unauthorized semantic request before runtime I/O."""


def aware_utc(value: datetime, *, field: str) -> datetime:
    """Require a timezone-aware datetime and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise SemanticTurnRejectedError(f"{field.replace(' ', '_')}_invalid")
    return value.astimezone(UTC)


def decode_request(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], SemanticTurnRequest, datetime]:
    """Decode one semantic request envelope and validate its temporal bindings."""
    try:
        envelope = OPERATOR_REQUEST_CONSUMER_V18.decode_mapping(payload)
        if envelope.get("request_kind") != "semantic_query":
            raise SemanticTurnRejectedError("semantic_request_kind_required")
        semantic_turn = envelope.get("semantic_turn")
        if not isinstance(semantic_turn, dict):
            raise SemanticTurnRejectedError("semantic_turn_required")
        request = SemanticTurnRequest.model_validate(semantic_turn)
        validate_investigation_continuation(request)
        requested_at_raw = envelope["requested_at"]
        if not isinstance(requested_at_raw, str):
            raise SemanticTurnRejectedError("semantic_requested_at_invalid")
        requested_at = aware_utc(
            datetime.fromisoformat(requested_at_raw.replace("Z", "+00:00")),
            field="semantic requested_at",
        )
        aware_utc(request.deadline_at, field="semantic deadline_at")
        return envelope, request, requested_at
    except SemanticTurnRejectedError:
        raise
    except Exception as exc:
        raise SemanticTurnRejectedError("semantic_request_invalid") from exc


def principal(request: SemanticTurnRequest) -> Principal:
    """Bind the highest ordinary role without granting BreakGlass authority."""
    ordinary_roles = [role for role in _ROLE_ORDER if role in request.principal.roles]
    if not ordinary_roles:
        raise SemanticTurnRejectedError("semantic_break_glass_only")
    selected = ordinary_roles[-1]
    return Principal(
        id=request.principal.subject_id,
        role=_ROLE_MAP[selected],
        groups=frozenset(request.principal.groups),
    )


def prior_turns(
    request: SemanticTurnRequest,
    *,
    requested_at: datetime,
) -> tuple[Turn, ...]:
    """Build bounded prior turns and retain the trusted context anchor last."""
    turns = [
        Turn(
            turn_id=f"{request.turn_id}:prior:{index}",
            direction="inbound" if item.role == "user" else "outbound",
            content=item.content,
            timestamp=requested_at,
        )
        for index, item in enumerate(request.prior_turns)
    ]
    anchor = bound_context_turn(request, requested_at=requested_at)
    if anchor is not None:
        turns.append(anchor)
    return tuple(turns)


def bound_context_turn(
    request: SemanticTurnRequest,
    *,
    requested_at: datetime,
) -> Turn | None:
    """Render one server-bound context anchor for the planner's context window."""
    binding = request.bound_context
    if binding is None:
        return None
    fields = [f"kind={binding.kind}"]
    if binding.incident_id is not None:
        fields.append(f"incident_id={binding.incident_id}")
    if binding.correlation_id is not None:
        fields.append(f"correlation_id={binding.correlation_id}")
    return Turn(
        turn_id=f"{request.turn_id}:bound-context",
        direction="system",
        content="Bound conversation context: " + ", ".join(fields),
        timestamp=requested_at,
    )


def bound_incident(request: SemanticTurnRequest) -> BoundIncident | None:
    """Expose the conversation's incident identity to planning as trusted input."""
    binding = request.bound_context
    if (
        binding is None
        or binding.kind != "incident"
        or binding.incident_id is None
        or binding.correlation_id is None
    ):
        return None
    return BoundIncident(
        incident_id=canonical_incident_id(binding.incident_id),
        correlation_id=binding.correlation_id,
    )


def bound_resource_context(request: SemanticTurnRequest) -> BoundResourceContext | None:
    """Expose only the exact server-selected screen or group scope to planning."""
    binding = request.bound_context
    if binding is None or binding.kind == "incident":
        return None
    if binding.kind == "screen" and binding.screen_id is not None:
        return BoundResourceContext(
            kind="screen",
            screen_id=binding.screen_id,
            resource_ids=binding.resource_ids,
            principal_id=binding.principal_id or "",
            principal_scope_digest=binding.principal_scope_digest or "",
            ontology_release_digest=binding.ontology_release_digest or "",
            source_generation=binding.source_generation or "",
            selection_digest=binding.selection_digest or "",
            selection_token=binding.selection_token or "",
            complete=binding.complete is True,
        )
    if binding.kind == "resource_group" and binding.resource_group_id is not None:
        return BoundResourceContext(
            kind="resource_group",
            resource_group_id=binding.resource_group_id,
            resource_ids=binding.resource_ids,
            principal_id=binding.principal_id or "",
            principal_scope_digest=binding.principal_scope_digest or "",
            ontology_release_digest=binding.ontology_release_digest or "",
            source_generation=binding.source_generation or "",
            selection_digest=binding.selection_digest or "",
            selection_token=binding.selection_token or "",
            complete=binding.complete is True,
        )
    return None


def validate_investigation_continuation(request: SemanticTurnRequest) -> None:
    """Reject a continuation that does not precede the current turn in this session."""
    continuation = request.investigation_continuation
    if continuation is None:
        return
    if (
        continuation.source_session_id != request.session_id
        or continuation.source_turn_sequence >= request.turn_sequence
    ):
        raise SemanticTurnRejectedError("semantic_investigation_continuation_mismatched")


def bound_investigation_continuation(
    request: SemanticTurnRequest,
) -> BoundInvestigationContinuation | None:
    """Project the validated continuation into the planner's immutable binding."""
    continuation = request.investigation_continuation
    if continuation is None:
        return None
    return BoundInvestigationContinuation(
        source_session_id=continuation.source_session_id,
        source_turn_id=continuation.source_turn_id,
        source_turn_sequence=continuation.source_turn_sequence,
        target_type=continuation.target_type,
        target_value=continuation.target_value,
        recovery_measure_concepts=continuation.recovery_measure_concepts,
        baseline_start=continuation.baseline_start,
        baseline_end=continuation.baseline_end,
        initial_observation_cutoff=continuation.initial_observation_cutoff,
        ontology_release_digest=continuation.ontology_release_digest,
        principal_manifest_digest=continuation.principal_manifest_digest,
        source_frame_digest=continuation.source_frame_digest,
        source_plan_digest=continuation.source_plan_digest,
        source_execution_receipt_digest=continuation.source_execution_receipt_digest,
    )


def canonical_incident_id(value: str) -> str:
    """Normalize a UUID when possible while preserving legacy incident identities."""
    try:
        return str(UUID(value))
    except ValueError:
        return value
