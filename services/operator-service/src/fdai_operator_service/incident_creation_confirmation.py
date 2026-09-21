"""Server-side confirmation of one durable semantic Incident draft."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts.incident_creation import (
    INCIDENT_CREATE_ACTION_TYPE,
    IncidentCreationConfirmationBody,
    IncidentCreationDraft,
    IncidentCreationRequest,
    build_incident_creation_request,
)
from fdai_service_contracts.operator import OperatorPrincipalKind, OperatorRole
from pydantic import ValidationError

from fdai_operator_service.action_confirmation_source import (
    validate_browser_action_confirmation,
)
from fdai_operator_service.families.conversation.contracts import (
    ActionConfirmationBody,
    ConversationBoundaryError,
    ConversationResponse,
    JsonObject,
    OutboxReceipt,
    PrincipalScope,
)
from fdai_operator_service.postgres_family_models import ActionProposalClaim
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
)

_ROLE_RANK = {
    OperatorRole.READER: 0,
    OperatorRole.CONTRIBUTOR: 1,
    OperatorRole.APPROVER: 2,
    OperatorRole.OWNER: 3,
    OperatorRole.BREAK_GLASS: -1,
}


@dataclass(frozen=True, slots=True)
class IncidentCreationConfirmationService:
    """Revalidate and durably accept one principal-owned semantic draft."""

    store: PostgresFamilyStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def confirm(
        self,
        *,
        scope: PrincipalScope,
        body: ActionConfirmationBody,
    ) -> OutboxReceipt:
        """Resolve the canonical source and persist an authority-free request."""

        principal_roles = _authorized_roles(scope)
        try:
            source = await self.store.read_semantic_action_draft_by_key(
                principal_id=scope.subject_id,
                idempotency_key=body.idempotency_key,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise ConversationBoundaryError(
                503,
                "incident_draft_unavailable",
                "authoritative Incident creation draft is unavailable",
            ) from exc
        if source is None:
            raise ConversationBoundaryError(
                409,
                "incident_draft_not_found",
                "the confirmed Incident draft is unavailable or stale",
            )
        confirmed_at = self.clock()
        if confirmed_at.tzinfo is None or confirmed_at.utcoffset() is None:
            raise ConversationBoundaryError(
                503,
                "incident_confirmation_unavailable",
                "the Incident confirmation clock is invalid",
            )
        request_id = _source_id(source, "request_id")
        projection_id = _source_id(source, "projection_id")
        correlation_id = source.get("correlation_id")
        internal_source: dict[str, object]
        response_message: str
        expires_at: datetime | None = None
        if body.action_type == INCIDENT_CREATE_ACTION_TYPE:
            try:
                incident_body = IncidentCreationConfirmationBody.model_validate(
                    body.model_dump(mode="json")
                )
            except ValidationError as exc:
                raise ConversationBoundaryError(
                    400,
                    "invalid_incident_confirmation",
                    "incident creation confirmation is invalid",
                ) from exc
            draft = validate_incident_confirmation_source(incident_body, source)
            expires_at = draft.expires_at
            internal_source = {
                "incident_creation_draft": draft.model_dump(mode="json"),
            }
            response_message = (
                "Incident creation request queued. Creation is complete only after "
                "the Incident appears in the authoritative roster."
            )
        else:
            intent = validate_browser_action_confirmation(
                body,
                source,
                principal_id=scope.subject_id,
            )
            internal_source = {"ontology_intent": intent.model_dump(mode="json")}
            response_message = (
                "Action request queued for the governed decision pipeline. "
                "HTTP acceptance is not execution success."
            )
        payload = {
            "idempotency_key": body.idempotency_key,
            "principal_roles": [role.value for role in principal_roles],
            "principal_kind": scope.principal_kind.value,
            "body": {
                **body.model_dump(mode="json"),
                "request_id": request_id,
                "projection_id": projection_id,
                **internal_source,
            },
        }
        storage_key = _confirmation_storage_key(scope.subject_id, body.idempotency_key)
        try:
            if expires_at is not None and confirmed_at > expires_at:
                existing = await self.store.read_proposal(
                    family="conversation",
                    idempotency_key=storage_key,
                )
                if existing is None:
                    raise ConversationBoundaryError(
                        409,
                        "incident_confirmation_expired",
                        "the action draft expired; prepare a new request",
                    )
                stored = _matching_existing_confirmation(
                    existing,
                    principal_id=scope.subject_id,
                    idempotency_key=storage_key,
                    payload=payload,
                )
            else:
                stored = await self.store.append_proposal(
                    family="conversation",
                    operation="chat.action.confirm",
                    principal_id=scope.subject_id,
                    idempotency_key=storage_key,
                    payload=payload,
                    accepted_at=confirmed_at,
                )
        except PostgresProposalConflict as exc:
            raise ConversationBoundaryError(
                409,
                "incident_confirmation_conflict",
                "the Incident confirmation key conflicts with another request",
            ) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise ConversationBoundaryError(
                503,
                "incident_confirmation_unavailable",
                "the Incident creation request could not be durably queued",
            ) from exc
        dispatch_status = stored.record.get("dispatch_status")
        response_body: JsonObject = {
            "submitted": True,
            "created": False,
            "action_type": body.action_type,
            "correlation_id": (correlation_id if isinstance(correlation_id, str) else request_id),
            "request_id": stored.proposal_id,
            "dispatch_status": (dispatch_status if isinstance(dispatch_status, str) else "pending"),
            "accepted_at": stored.accepted_at,
            "duplicate": stored.duplicate,
            "message": response_message,
        }
        return OutboxReceipt(
            proposal_id=stored.proposal_id,
            duplicate=stored.duplicate,
            response=ConversationResponse(body=response_body, status_code=202),
        )


def _authorized_roles(scope: PrincipalScope) -> tuple[OperatorRole, ...]:
    if scope.principal_kind is not OperatorPrincipalKind.HUMAN:
        raise ConversationBoundaryError(
            403,
            "incident_confirmation_forbidden",
            "incident creation confirmation requires a human principal",
        )
    try:
        roles = tuple(
            sorted(
                {OperatorRole(role) for role in scope.roles},
                key=_ROLE_RANK.__getitem__,
            )
        )
    except ValueError as exc:
        raise ConversationBoundaryError(
            403,
            "incident_confirmation_forbidden",
            "incident creation confirmation requires a recognized operator role",
        ) from exc
    if (
        OperatorRole.BREAK_GLASS in roles
        or max((_ROLE_RANK[role] for role in roles), default=-1)
        < _ROLE_RANK[OperatorRole.CONTRIBUTOR]
    ):
        raise ConversationBoundaryError(
            403,
            "incident_confirmation_forbidden",
            "incident creation confirmation requires a Contributor-or-higher principal",
        )
    return roles


def _source_id(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ConversationBoundaryError(
            409,
            "incident_draft_invalid",
            "the Incident creation draft source is invalid",
        )
    return value


def _confirmation_storage_key(principal_id: str, source_key: str) -> str:
    digest = hashlib.sha256(f"{principal_id}\0{source_key}".encode()).hexdigest()
    return f"action-confirmation:{digest}"


def _matching_existing_confirmation(
    stored: StoredProposal,
    *,
    principal_id: str,
    idempotency_key: str,
    payload: Mapping[str, object],
) -> StoredProposal:
    record = getattr(stored, "record", None)
    if (
        not isinstance(record, Mapping)
        or record.get("family") != "conversation"
        or record.get("operation") != "chat.action.confirm"
        or record.get("principal_id") != principal_id
        or record.get("idempotency_key") != idempotency_key
        or record.get("payload") != payload
    ):
        raise PostgresProposalConflict(
            "idempotency key conflicts with a different durable Operator proposal"
        )
    return stored


def validate_incident_confirmation_source(
    body: IncidentCreationConfirmationBody,
    source_projection: Mapping[str, object],
) -> IncidentCreationDraft:
    """Require an exact semantic Incident draft without trusting the browser."""

    payload = source_projection.get("payload")
    semantic = source_projection.get("semantic_result")
    if not isinstance(payload, Mapping) or not isinstance(semantic, Mapping):
        raise ConversationBoundaryError(
            409,
            "incident_draft_invalid",
            "the Incident creation draft source is invalid",
        )
    try:
        draft = IncidentCreationDraft.model_validate(payload.get("incident_creation_draft"))
    except ValidationError as exc:
        raise ConversationBoundaryError(
            409,
            "incident_draft_invalid",
            "the Incident creation draft source is invalid",
        ) from exc
    if (
        source_projection.get("status") != "action_draft"
        or source_projection.get("idempotency_key") != draft.idempotency_key
        or semantic.get("disposition") != "action_draft"
        or semantic.get("session_id") != draft.session_id
        or body.action_type != draft.action_type
        or body.arguments.model_dump(mode="json") != draft.arguments.model_dump(mode="json")
        or body.session_id != draft.session_id
        or body.idempotency_key != draft.idempotency_key
    ):
        raise ConversationBoundaryError(
            409,
            "incident_confirmation_mismatch",
            "the Incident confirmation does not match its semantic draft",
        )
    return draft


def incident_creation_request_from_claim(
    claim: ActionProposalClaim,
    *,
    source_projection: Mapping[str, object],
) -> IncidentCreationRequest:
    """Build one versioned Incident creation request from a durable confirmation."""

    body_value = claim.payload.get("body")
    principal_roles = claim.payload.get("principal_roles")
    principal_kind = claim.payload.get("principal_kind")
    if (
        not isinstance(body_value, Mapping)
        or not isinstance(principal_roles, list | tuple)
        or not all(isinstance(role, str) for role in principal_roles)
        or principal_kind != OperatorPrincipalKind.HUMAN.value
    ):
        raise ValueError("incident creation confirmation record is malformed")
    expected_body_fields = {
        "action_type",
        "arguments",
        "session_id",
        "idempotency_key",
        "request_id",
        "projection_id",
        "incident_creation_draft",
    }
    if set(body_value) != expected_body_fields:
        raise ValueError("incident creation confirmation fields are malformed")
    public_body = IncidentCreationConfirmationBody.model_validate(
        {
            key: value
            for key, value in body_value.items()
            if key in {"action_type", "arguments", "session_id", "idempotency_key"}
        }
    )
    if claim.payload.get("idempotency_key") != public_body.idempotency_key:
        raise ValueError("incident creation confirmation idempotency is malformed")
    try:
        draft = validate_incident_confirmation_source(public_body, source_projection)
    except ConversationBoundaryError as exc:
        raise ValueError("incident creation source validation failed") from exc
    if body_value.get("incident_creation_draft") != draft.model_dump(mode="json"):
        raise ValueError("incident creation draft changed after durable acceptance")
    request_id = body_value.get("request_id")
    projection_id = body_value.get("projection_id")
    if (
        request_id != source_projection.get("request_id")
        or projection_id != source_projection.get("projection_id")
        or not isinstance(request_id, str)
        or not isinstance(projection_id, str)
    ):
        raise ValueError("incident creation source identity is malformed")
    return build_incident_creation_request(
        request_id=request_id,
        source_request_id=request_id,
        source_projection_id=projection_id,
        principal_id=claim.principal_id,
        principal_roles=tuple(OperatorRole(role) for role in principal_roles),
        idempotency_key=public_body.idempotency_key,
        session_id=public_body.session_id,
        arguments=draft.arguments,
        source_input_digest=draft.source_input_digest,
        draft_digest=draft.draft_digest,
        draft_expires_at=draft.expires_at,
        confirmed_at=datetime.fromisoformat(claim.accepted_at.replace("Z", "+00:00")),
    )
