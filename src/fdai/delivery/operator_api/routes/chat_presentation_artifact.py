"""Compile validated presentation plans from immutable chat evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from fdai.core.conversation.answer_plan import AnswerPlan
from fdai.delivery.operator_api.routes.chat_presentation_artifact_common import bounded_refs
from fdai.delivery.operator_api.routes.chat_presentation_contract import parse_presentation_plan
from fdai.delivery.operator_api.routes.chat_presentation_health_artifact import (
    subscription_health_blocks,
)
from fdai.delivery.operator_api.routes.chat_presentation_inventory_artifact import (
    inventory_blocks,
)
from fdai.delivery.operator_api.routes.chat_presentation_profiles import presentation_profile

_VERIFIED_PRESENTATION_STATUSES: Final = frozenset(
    {"verified", "consistent", "corrected", "unverified"}
)
_MAX_PRESENTATION_ARTIFACT_BYTES: Final = 48 * 1024


def response_presentation_artifact(
    view_context: Mapping[str, Any],
    *,
    answer_plan: AnswerPlan,
    verification_status: str,
    evidence_refs: Sequence[str],
    locale: str | None,
) -> dict[str, object] | None:
    """Return one evidence-bound mixed artifact or the canonical text fallback."""

    if verification_status not in _VERIFIED_PRESENTATION_STATUSES:
        return None
    refs = bounded_refs(evidence_refs)
    if not refs:
        return None
    profile = presentation_profile(view_context, answer_plan)
    raw_plan = view_context.get("_presentation_plan")
    if profile is None or not isinstance(raw_plan, Mapping):
        return None
    plan = parse_presentation_plan(raw_plan, profile)
    if plan is None:
        return None
    evidence = view_context.get("_tool_evidence")
    if not isinstance(evidence, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if evidence.get("tool") == "query_subscription_health":
        blocks = subscription_health_blocks(
            evidence,
            plan.placements,
            refs=refs,
            korean=korean,
            verification_status=verification_status,
        )
    elif evidence.get("tool") == "query_inventory":
        blocks = inventory_blocks(
            evidence,
            plan.placements,
            refs=refs,
            korean=korean,
            verification_status=verification_status,
        )
    else:
        return None
    if not blocks or len(blocks) != len(plan.placements):
        return None
    artifact: dict[str, object] = {
        "schema_version": 1,
        "layout": "stack",
        "blocks": blocks,
        "evidence_refs": list(refs),
    }
    if (
        len(json.dumps(artifact, ensure_ascii=False).encode("utf-8"))
        > _MAX_PRESENTATION_ARTIFACT_BYTES
    ):
        return None
    return artifact


__all__ = ["response_presentation_artifact"]
