"""Validate browser and outbox action confirmations against durable semantic source."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_service_contracts.action_intent import OntologyActionIntent
from pydantic import ValidationError

from fdai_operator_service.families.conversation.contracts import (
    ActionConfirmationBody,
    ConversationBoundaryError,
)


def validate_browser_action_confirmation(
    body: ActionConfirmationBody,
    source_projection: Mapping[str, object],
    *,
    principal_id: str,
) -> OntologyActionIntent:
    """Bind a public confirmation to its server-owned ontology action intent."""

    semantic = source_projection.get("semantic_result")
    if not isinstance(semantic, Mapping):
        raise ConversationBoundaryError(
            409,
            "action_draft_invalid",
            "the action draft source is invalid",
        )
    try:
        intent = OntologyActionIntent.model_validate(semantic.get("action_intent"))
    except ValidationError as exc:
        raise ConversationBoundaryError(
            409,
            "action_draft_invalid",
            "the action draft source is invalid",
        ) from exc
    if (
        source_projection.get("status") != "action_draft"
        or source_projection.get("idempotency_key") != body.idempotency_key
        or semantic.get("disposition") != "action_draft"
        or semantic.get("session_id") != body.session_id
        or intent.actor_ref != f"operator:{principal_id}"
        or intent.action_type_name != body.action_type
        or intent.arguments != body.arguments
    ):
        raise ConversationBoundaryError(
            409,
            "action_confirmation_mismatch",
            "the action confirmation does not match its semantic draft",
        )
    return intent


def validate_action_confirmation_source(
    body: Mapping[str, object],
    source_projection: Mapping[str, object],
    *,
    principal_id: str,
) -> OntologyActionIntent:
    """Require one exact durable action draft owned by the authenticated principal."""

    intent = OntologyActionIntent.model_validate(body.get("ontology_intent"))
    request_id = body.get("request_id")
    projection_id = body.get("projection_id")
    idempotency_key = body.get("idempotency_key")
    session_id = body.get("session_id")
    semantic_result = source_projection.get("semantic_result")
    if not isinstance(semantic_result, Mapping):
        raise ValueError("semantic action draft source is malformed")
    source_intent = OntologyActionIntent.model_validate(semantic_result.get("action_intent"))
    if (
        intent.actor_ref != f"operator:{principal_id}"
        or source_intent != intent
        or source_projection.get("request_id") != request_id
        or source_projection.get("projection_id") != projection_id
        or source_projection.get("idempotency_key") != idempotency_key
        or source_projection.get("status") != "action_draft"
        or semantic_result.get("disposition") != "action_draft"
        or semantic_result.get("session_id") != session_id
    ):
        raise ValueError("action confirmation does not match its durable semantic source")
    return intent


__all__ = [
    "validate_action_confirmation_source",
    "validate_browser_action_confirmation",
]
