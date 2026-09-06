"""Build versioned semantic-turn envelopes from authorized conversation proposals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.families.conversation.contracts import ConversationProposal
from fdai_service_contracts import (
    JsonSchemaContractValidator,
    OperatorPrincipalKind,
    OperatorRole,
    PackageResourceSchemaRegistry,
    SemanticBoundContext,
    SemanticInvestigationContinuation,
    SemanticPlanningProfile,
    SemanticPriorTurn,
    SemanticTurnPrincipal,
    SemanticTurnRequest,
    canonical_ordinary_role,
    context_selection_digest,
)
from fdai_service_contracts.adaptive_answer import AdaptiveAgentName
from fdai_service_contracts.adaptive_relationship import (
    AdaptiveRelationshipProof,
    AdaptiveRelationshipUnknownReason,
)
from fdai_service_contracts.codec import MAX_WIRE_BYTES, encode_wire_object
from pydantic import TypeAdapter

_IDENTITY_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_DEFAULT_DEADLINE_SECONDS = 90
_MAX_DEADLINE_SECONDS = 90
_TARGET_AGENT: TypeAdapter[AdaptiveAgentName] = TypeAdapter(AdaptiveAgentName)

Clock = Callable[[], datetime]


class SemanticTurnEnvelopeBuilder:
    """Construct no-authority requests with retry-stable identities and bounded routing."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        selection_registry: ContextSelectionRegistry | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
        self._selection_registry = selection_registry

    def build(
        self,
        proposal: ConversationProposal,
        *,
        investigation_continuation: SemanticInvestigationContinuation | None = None,
        relationship_proof: AdaptiveRelationshipProof | None = None,
        relationship_unknown_reason: AdaptiveRelationshipUnknownReason | None = None,
    ) -> dict[str, object]:
        """Validate an authorized proposal without treating role selection as a relationship."""
        if proposal.operation != "chat.stream":
            raise ValueError("semantic turn builder accepts only chat.stream proposals")
        if any(
            key in proposal.body
            for key in (
                "relationship",
                "relationship_context",
                "relationship_proof",
                "verified_relationship",
                "dialogue_profile",
                "relationship_unknown_reason",
            )
        ):
            raise ValueError("dialogue relationships require authoritative server verification")
        target_agent = _TARGET_AGENT.validate_python(proposal.body.get("target_agent", "Bragi"))
        if relationship_proof is not None and (
            relationship_proof.principal_id != proposal.scope.subject_id
            or relationship_proof.target_agent != target_agent
        ):
            raise ValueError("relationship proof MUST match the authenticated principal and target")
        requested_at = _aware_utc(self._clock())
        identity_seed = f"{proposal.scope.subject_id}\0{proposal.idempotency_key}"
        request_id = _request_id(proposal, identity_seed)
        session_id = _session_id(proposal, identity_seed)
        turn_id = str(uuid5(_IDENTITY_NAMESPACE, f"turn\0{identity_seed}"))
        roles = _authorized_roles(proposal)
        purpose = _optional_text(proposal.body, "purpose", default="operations-review")
        semantic_turn = SemanticTurnRequest(
            utterance=_required_text(proposal.body, "prompt"),
            principal=SemanticTurnPrincipal(
                subject_id=proposal.scope.subject_id,
                roles=roles,
                principal_kind=proposal.scope.principal_kind,
                groups=tuple(sorted(proposal.scope.groups)),
            ),
            session_id=session_id,
            turn_id=turn_id,
            turn_sequence=_turn_sequence(proposal.body),
            locale=_optional_text(proposal.body, "locale", default="en"),
            purpose=purpose,
            deadline_at=_deadline(proposal.body, requested_at),
            view_context_digest=_optional_digest(proposal.body.get("view_context")),
            bound_context=_bound_context(
                proposal.body.get("conversation_context"),
                principal_id=proposal.scope.subject_id,
                role=_highest_ordinary_role(roles),
                purpose=purpose,
                selection_registry=self._selection_registry,
            ),
            investigation_continuation=investigation_continuation,
            prior_turns=_prior_turns(proposal.body.get("history")),
            planning_profile=_planning_profile(proposal.body),
            include_model_trace=proposal.body.get("include_model_trace") is True,
            cancelled=proposal.cancellation,
            target_agent=target_agent,
            relationship_proof=relationship_proof,
            relationship_unknown_reason=relationship_unknown_reason,
        )
        semantic_payload = semantic_turn.model_dump(mode="json", exclude_none=True)
        schema_version = (
            "1.6.0"
            if (
                "target_agent" in proposal.body
                or relationship_proof is not None
                or relationship_unknown_reason is not None
                or proposal.scope.groups
            )
            else "1.5.0"
        )
        if schema_version == "1.5.0":
            semantic_payload.pop("target_agent", None)
        bound_context_payload = semantic_payload.get("bound_context")
        if (
            isinstance(bound_context_payload, dict)
            and bound_context_payload.get("kind") == "incident"
        ):
            bound_context_payload.pop("resource_ids", None)
        if proposal.scope.principal_kind is OperatorPrincipalKind.HUMAN:
            principal_payload = semantic_payload.get("principal")
            if isinstance(principal_payload, dict):
                principal_payload.pop("principal_kind", None)
        principal_payload = semantic_payload.get("principal")
        if isinstance(principal_payload, dict) and not principal_payload.get("groups"):
            principal_payload.pop("groups", None)
        envelope: dict[str, object] = {
            "schema_version": schema_version,
            "request_id": request_id,
            "correlation_id": f"semantic-turn:{request_id}",
            "idempotency_key": proposal.idempotency_key,
            "resource_ref": f"operator-conversation:{_digest_text(session_id)[:32]}",
            "request_kind": "semantic_query",
            "requested_at": requested_at.isoformat(),
            "semantic_turn": semantic_payload,
        }
        self._validator.validate("operator-core-request", envelope, version=schema_version)
        if len(encode_wire_object(envelope)) > MAX_WIRE_BYTES:
            raise ValueError("semantic turn exceeds the 256 KiB wire bound")
        return envelope


def _request_id(proposal: ConversationProposal, identity_seed: str) -> str:
    supplied = proposal.body.get("request_id")
    if supplied is None:
        return str(uuid5(_IDENTITY_NAMESPACE, f"request\0{identity_seed}"))
    if not isinstance(supplied, str):
        raise ValueError("request_id MUST be a UUID string")
    try:
        return str(UUID(supplied))
    except ValueError as exc:
        raise ValueError("request_id MUST be a UUID string") from exc


def _authorized_roles(proposal: ConversationProposal) -> tuple[OperatorRole, ...]:
    try:
        roles = {OperatorRole(role) for role in proposal.scope.roles}
    except ValueError as exc:
        raise ValueError("principal scope contains an unsupported Operator role") from exc
    if not roles:
        raise ValueError("principal scope MUST contain an authorized Operator role")
    order = {role: index for index, role in enumerate(OperatorRole)}
    return tuple(sorted(roles, key=order.__getitem__))


def _session_id(proposal: ConversationProposal, identity_seed: str) -> str:
    supplied = proposal.body.get("session_id")
    conversation_id = proposal.body.get("conversation_id")
    if (
        isinstance(supplied, str)
        and supplied.strip()
        and isinstance(conversation_id, str)
        and conversation_id.strip()
        and supplied.strip() != conversation_id.strip()
    ):
        raise ValueError("session_id and conversation_id MUST identify the same session")
    for candidate in (supplied, conversation_id):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return str(uuid5(_IDENTITY_NAMESPACE, f"session\0{identity_seed}"))


def _turn_sequence(body: Mapping[str, object]) -> int:
    value = body.get("turn_sequence", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("turn_sequence MUST be a non-negative integer")
    return value


def _planning_profile(body: Mapping[str, object]) -> SemanticPlanningProfile:
    value = body.get(
        "semantic_planning_profile",
        SemanticPlanningProfile.INTERACTIVE.value,
    )
    if not isinstance(value, str):
        raise ValueError("semantic_planning_profile is unsupported")
    try:
        return SemanticPlanningProfile(value)
    except ValueError as exc:
        raise ValueError("semantic_planning_profile is unsupported") from exc


def _deadline(body: Mapping[str, object], requested_at: datetime) -> datetime:
    value = body.get("deadline_at")
    if value is None:
        return requested_at + timedelta(seconds=_DEFAULT_DEADLINE_SECONDS)
    if not isinstance(value, str):
        raise ValueError("deadline_at MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("deadline_at MUST be an RFC 3339 string") from exc
    deadline = _aware_utc(parsed)
    if deadline <= requested_at:
        raise ValueError("deadline_at MUST be later than requested_at")
    if deadline > requested_at + timedelta(seconds=_MAX_DEADLINE_SECONDS):
        raise ValueError("deadline_at MUST be at most 90 seconds after requested_at")
    return deadline


def _prior_turns(value: object) -> tuple[SemanticPriorTurn, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("history MUST be an array")
    turns: list[SemanticPriorTurn] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("history items MUST be objects")
        turns.append(SemanticPriorTurn.model_validate(item))
    return tuple(turns)


def _bound_context(
    value: object,
    *,
    principal_id: str,
    role: str,
    purpose: str,
    selection_registry: ContextSelectionRegistry | None,
) -> SemanticBoundContext | None:
    """Resolve opaque selections and accept only server-owned resource scopes."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("conversation_context MUST be an object")
    kind = value.get("kind")
    if kind not in {"incident", "screen", "resource_group"}:
        return None
    if kind in {"screen", "resource_group"}:
        if selection_registry is None:
            raise ValueError("conversation_context selection token is unavailable")
        if any(
            key in value
            for key in (
                "resource_ids",
                "screen_id",
                "resource_group_id",
                "id",
                "principal_id",
                "principal_scope_digest",
                "ontology_release_digest",
                "source_generation",
                "selection_digest",
                "complete",
            )
        ):
            raise ValueError("conversation_context resource identity MUST use its selection token")
        token = value.get("selection_token")
        selection = selection_registry.resolve(
            token if isinstance(token, str) else "",
            principal_id=principal_id,
            role=role,
            purpose=purpose,
        )
        if selection is None or selection.get("kind") != kind:
            raise ValueError("conversation_context selection token is invalid or expired")
        if kind == "screen":
            screen_id = selection.get("screen_id")
            if not isinstance(screen_id, str):
                raise ValueError("screen selection identity is invalid")
            context = SemanticBoundContext(
                kind="screen",
                screen_id=screen_id,
                selection_token=token,
                resource_ids=tuple(selection["resource_ids"]),
                **_context_identity_fields(selection, principal_id=principal_id),
            )
            _verify_context_selection_digest(context)
            return context
        resource_group_id = selection.get("resource_group_id")
        if not isinstance(resource_group_id, str):
            raise ValueError("resource-group selection identity is invalid")
        context = SemanticBoundContext(
            kind="resource_group",
            resource_group_id=resource_group_id,
            selection_token=token,
            resource_ids=tuple(selection["resource_ids"]),
            **_context_identity_fields(selection, principal_id=principal_id),
        )
        _verify_context_selection_digest(context)
        return context
    incident_id = value.get("incident_id")
    correlation_id = value.get("correlation_id")
    if incident_id is None and correlation_id is None:
        return None
    return SemanticBoundContext(
        kind="incident",
        incident_id=incident_id if isinstance(incident_id, str) and incident_id else None,
        correlation_id=(
            correlation_id if isinstance(correlation_id, str) and correlation_id else None
        ),
    )


def _context_identity_fields(value: dict[str, object], *, principal_id: str) -> dict[str, Any]:
    """Require the server-issued identity envelope before accepting resource ids."""
    fields: dict[str, Any] = {
        "principal_id": value.get("principal_id"),
        "principal_scope_digest": value.get("principal_scope_digest"),
        "ontology_release_digest": value.get("ontology_release_digest"),
        "source_generation": value.get("source_generation"),
        "selection_digest": value.get("selection_digest"),
        "complete": value.get("complete"),
    }
    if fields["principal_id"] != principal_id or fields["complete"] is not True:
        raise ValueError(
            "conversation_context identity is not bound to the authenticated principal"
        )
    if any(
        not isinstance(fields[key], str) or not fields[key].strip()
        for key in fields
        if key != "complete"
    ):
        raise ValueError("conversation_context identity is incomplete")
    return fields


def _highest_ordinary_role(roles: tuple[OperatorRole, ...]) -> str:
    ordinary = [role for role in roles if role is not OperatorRole.BREAK_GLASS]
    if not ordinary:
        raise ValueError("principal scope MUST contain an ordinary query role")
    return canonical_ordinary_role(ordinary[-1])


def _verify_context_selection_digest(context: SemanticBoundContext) -> None:
    if context.kind == "incident":
        raise ValueError("incident context cannot carry a resource selection digest")
    expected = context_selection_digest(
        kind=context.kind,
        principal_id=context.principal_id or "",
        principal_scope_digest=context.principal_scope_digest or "",
        ontology_release_digest=context.ontology_release_digest or "",
        source_generation=context.source_generation or "",
        complete=context.complete is True,
        screen_id=context.screen_id,
        resource_group_id=context.resource_group_id,
        resource_ids=context.resource_ids,
    )
    if context.selection_digest != expected:
        raise ValueError("conversation_context selection digest does not match its identity")


def _required_text(body: Mapping[str, object], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_text(body: Mapping[str, object], key: str, *, default: str) -> str:
    value = body.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_digest(value: object) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("semantic turn clock values MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["SemanticTurnEnvelopeBuilder"]
