"""Validate and present the work progress fields of one stored semantic projection.

Core persists the plan-time pin, the enforcing turn budget, and applied operator-preference
receipts in the projection payload. They are presentation context, never evidence or authority,
so each field is validated on its own and dropped alone when malformed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_service_contracts.semantic_work_progress import (
    SemanticContextReceipt,
    TurnBudgetTelemetry,
    WorkProgressShape,
    derive_work_progress_shape,
    parse_context_receipts,
)
from pydantic import ValidationError

_LOGGER = logging.getLogger(__name__)


def persisted_work_progress_shape(projection: Mapping[str, object]) -> JsonObject | None:
    """Return the persisted pin when it still describes the stored read plan."""
    raw = _payload(projection).get("work_progress_shape")
    if raw is None:
        return None
    try:
        shape = WorkProgressShape.model_validate(raw)
    except ValidationError:
        _LOGGER.warning("semantic_work_progress_shape_rejected")
        return None
    semantic = projection.get("semantic_result")
    graph = semantic.get("intent_graph") if isinstance(semantic, Mapping) else None
    if graph is not None and derive_work_progress_shape(_graph_nodes(graph)) != shape:
        _LOGGER.warning("semantic_work_progress_shape_mismatched")
        return None
    return cast(JsonObject, shape.model_dump(mode="json"))


def work_progress_detail_fields(
    projection: Mapping[str, object],
    *,
    locale: str,
) -> JsonObject:
    """Return the optional trajectory fields in the shape the Console parses."""
    fields: dict[str, object] = {}
    shape = persisted_work_progress_shape(projection)
    if shape is not None:
        fields["work_progress_shape"] = shape
    budget = _turn_budget(_payload(projection).get("turn_budget"))
    if budget is not None:
        fields["turn_budget"] = budget
    receipts = _context_receipts(_payload(projection).get("context_receipts"), locale=locale)
    if receipts:
        fields["context_receipts"] = receipts
    return cast(JsonObject, fields)


def _payload(projection: Mapping[str, object]) -> Mapping[str, object]:
    payload = projection.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _graph_nodes(graph: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Read the plan DAG from the stored intent graph; malformed input yields no nodes."""
    goals = graph.get("goals") if isinstance(graph, Mapping) else None
    if not isinstance(goals, list):
        return ()
    nodes: list[tuple[str, tuple[str, ...]]] = []
    for goal in goals:
        goal_id = goal.get("goal_id") if isinstance(goal, Mapping) else None
        depends_on = goal.get("depends_on", []) if isinstance(goal, Mapping) else None
        if (
            not isinstance(goal_id, str)
            or not isinstance(depends_on, list)
            or any(not isinstance(item, str) for item in depends_on)
        ):
            return ()
        nodes.append((goal_id, tuple(depends_on)))
    return tuple(nodes)


def _turn_budget(raw: object) -> JsonObject | None:
    if raw is None:
        return None
    try:
        budget = TurnBudgetTelemetry.model_validate(raw)
    except ValidationError:
        _LOGGER.warning("semantic_turn_budget_rejected")
        return None
    return cast(JsonObject, budget.model_dump(mode="json", exclude_none=True))


def _context_receipts(raw: object, *, locale: str) -> list[JsonObject]:
    if raw is None:
        return []
    try:
        receipts = parse_context_receipts(raw)
    except ValueError:
        _LOGGER.warning("semantic_context_receipts_rejected")
        return []
    korean = locale.casefold().startswith("ko")
    return [_context_receipt(receipt, korean=korean) for receipt in receipts]


def _context_receipt(receipt: SemanticContextReceipt, *, korean: bool) -> JsonObject:
    wire = receipt.model_dump(mode="json")
    tier = receipt.value.value.upper()
    return cast(
        JsonObject,
        {
            "receipt_id": wire["receipt_id"],
            "kind": wire["kind"],
            "digest": wire["digest"],
            "observed_at": wire["observed_at"],
            "freshness": wire["freshness"],
            "label": f"대화 모델: {tier}" if korean else f"Conversation model: {tier}",
        },
    )


__all__ = ["persisted_work_progress_shape", "work_progress_detail_fields"]
