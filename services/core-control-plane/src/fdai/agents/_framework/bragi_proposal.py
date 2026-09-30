"""Typed action-proposal construction for the Bragi translator."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from typing import Any

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.agents._framework.bragi_routing import action_from_semantic_judgment
from fdai.agents._framework.topics import stable_idempotency_key
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
    judgment: SemanticJudgmentProposal,
    action_type_names: Collection[str],
    initiator_role: str | None,
    pipeline_available: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build a typed proposal and its operator-facing status envelope."""
    role = _ROLE_BY_NAME.get(initiator_role.strip().lower()) if initiator_role else None
    if role is None or not has_capability((role,), _SUBMIT_CAPABILITY):
        return None, {
            "submitted": False,
            "abstain_reason": "rbac_role_floor",
            "required_role": "Contributor",
            "initiator_role": initiator_role,
            "correlation_id": _proposal_correlation_id(
                session_id=session_id,
                question=question,
                action_type="",
                resource_id="",
                initiator_principal=user_id,
                params={},
            ),
        }
    action_type, resource_id = action_from_semantic_judgment(judgment, action_type_names)
    question_digest = hashlib.sha256(question[:_MAX_QUESTION_CHARS].encode("utf-8")).hexdigest()
    session_digest = hashlib.sha256(session_id[:_MAX_SESSION_CHARS].encode("utf-8")).hexdigest()
    params = {
        "question_ref": f"bragi-question:sha256:{question_digest}",
        "session_ref": f"bragi-session:sha256:{session_digest}",
    }
    correlation_id = _proposal_correlation_id(
        session_id=session_id,
        question=question,
        action_type=action_type or "",
        resource_id=resource_id or "",
        initiator_principal=user_id,
        params=params,
    )
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
    if resource_id is None:
        return None, {
            "submitted": False,
            "held": True,
            "abstain_reason": "resource_target_required",
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
        "params": params,
    }
    return proposal, {
        "submitted": True,
        "correlation_id": correlation_id,
        "action_type": action_type,
        "initiator_principal": user_id,
    }


def _proposal_correlation_id(
    *,
    session_id: str,
    question: str,
    action_type: str,
    resource_id: str,
    initiator_principal: str,
    params: Mapping[str, Any],
) -> str:
    params_digest = hashlib.sha256(
        json.dumps(
            params,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    turn_key = hashlib.sha256(question[:_MAX_QUESTION_CHARS].encode("utf-8")).hexdigest()
    body = {
        "session_id": session_id[:_MAX_SESSION_CHARS],
        "turn": turn_key,
        "action_type": action_type,
        "resource_id": resource_id[:_MAX_RESOURCE_CHARS],
        "initiator_principal": hashlib.sha256(initiator_principal.encode("utf-8")).hexdigest(),
        "params_digest": f"sha256:{params_digest}",
    }
    return stable_idempotency_key("conv", body).replace("conv:", "conv-", 1)


__all__ = ["build_action_proposal"]
