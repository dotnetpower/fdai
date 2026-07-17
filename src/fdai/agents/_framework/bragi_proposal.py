"""Typed action-proposal construction for the Bragi translator."""

from __future__ import annotations

import uuid
from typing import Any

from fdai.agents._framework.bragi_routing import translate_action_intent
from fdai.core.rbac.roles import Capability, Role, has_capability

_MAX_QUESTION_CHARS = 2_000
_MAX_RESOURCE_CHARS = 200
_MAX_SESSION_CHARS = 200
_ROLE_BY_NAME: dict[str, Role] = {role.value.lower(): role for role in Role}
_SUBMIT_CAPABILITY = Capability.AUTHOR_DRAFT_PR


def build_action_proposal(
    *,
    session_id: str,
    user_id: str,
    question: str,
    initiator_role: str | None,
    pipeline_available: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build a typed proposal and its operator-facing status envelope."""
    correlation_id = f"conv-{uuid.uuid4()}"
    if initiator_role is not None:
        role = _ROLE_BY_NAME.get(initiator_role.strip().lower())
        if role is None or not has_capability((role,), _SUBMIT_CAPABILITY):
            return None, {
                "submitted": False,
                "abstain_reason": "rbac_role_floor",
                "required_role": "Contributor",
                "initiator_role": initiator_role,
                "correlation_id": correlation_id,
            }
    action_type, resource_id = translate_action_intent(question)
    if action_type is None:
        return None, {
            "submitted": False,
            "abstain_reason": "unmapped_action_intent",
            "correlation_id": correlation_id,
        }
    if not pipeline_available:
        return None, {
            "submitted": False,
            "abstain_reason": "requires_typed_pipeline",
            "correlation_id": correlation_id,
            "action_type": action_type,
        }
    proposal: dict[str, Any] = {
        "idempotency_key": correlation_id,
        "correlation_id": correlation_id,
        "initiator_principal": user_id,
        "operator_initiated": True,
        "action_type": action_type,
        "resource_id": resource_id[:_MAX_RESOURCE_CHARS] if resource_id else None,
        "event_type": "operator_request",
        "params": {
            "question": question[:_MAX_QUESTION_CHARS],
            "session_id": session_id[:_MAX_SESSION_CHARS],
        },
    }
    return proposal, {
        "submitted": True,
        "correlation_id": correlation_id,
        "action_type": action_type,
        "initiator_principal": user_id,
    }


__all__ = ["build_action_proposal"]
