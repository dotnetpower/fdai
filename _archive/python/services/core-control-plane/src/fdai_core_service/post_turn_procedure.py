"""Project content-free post-turn evidence from actually executed ontology plans."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping

from fdai.core.ontology_platform import QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryTable
from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    TaskStatus,
    content_digest,
)
from fdai_service_contracts.operator import OperatorPrincipalKind
from fdai_service_contracts.post_turn_review import (
    PostTurnProcedureReceipt,
    PostTurnToolReceipt,
)
from fdai_service_contracts.semantic_projection import semantic_projection_id
from fdai_service_contracts.semantic_turn import SemanticTurnRequest

_LOGGER = logging.getLogger(__name__)


class _ShapeDepthError(ValueError):
    pass


def bound_procedure_projection(projection: dict[str, object], *, maximum_bytes: int) -> int:
    """Omit only optional procedure metadata if it would exceed the existing wire budget."""
    if isinstance(maximum_bytes, bool) or maximum_bytes < 1:
        raise ValueError("maximum_bytes MUST be a positive integer")
    size = _projection_size(projection)
    payload = projection.get("payload")
    details = payload.get("technical_details") if isinstance(payload, Mapping) else None
    if (
        size > maximum_bytes
        and isinstance(payload, Mapping)
        and isinstance(details, Mapping)
        and "post_turn_procedure" in details
    ):
        retained = dict(details)
        del retained["post_turn_procedure"]
        projection["payload"] = {**payload, "technical_details": retained}
        projection["projection_id"] = semantic_projection_id(projection)
        _LOGGER.warning(
            "post_turn_procedure_unavailable",
            extra={"reason": "wire_budget_exceeded", "request_id": projection.get("request_id")},
        )
        size = _projection_size(projection)
    return size


def _projection_size(projection: Mapping[str, object]) -> int:
    return len(
        json.dumps(projection, allow_nan=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )


def execution_receipt_digest(execution: QueryPlanExecution) -> str:
    return content_digest(
        {
            "plan_digest": execution.plan_digest,
            "status": execution.status,
            "output_node_ids": execution.output_node_ids,
            "receipts": [receipt.model_dump(mode="json") for receipt in execution.receipts],
        }
    )


def with_post_turn_procedure(
    details: dict[str, object],
    request: SemanticTurnRequest,
    plan: OntologyQueryPlan,
    execution: QueryPlanExecution,
) -> dict[str, object]:
    """Keep excluded observations explicit; never include argument values or turn bodies."""
    if not isinstance(plan, OntologyQueryPlan):
        return {
            **details,
            "post_turn_procedure": {
                "kind": "unavailable",
                "reason": "typed_verified_plan_required",
            },
        }
    reason = _unavailable_reason(request, plan, execution)
    if reason is not None:
        return {**details, "post_turn_procedure": {"kind": "unavailable", "reason": reason}}
    positions = {node.node_id: position for position, node in enumerate(plan.nodes)}
    shape: list[dict[str, object]] = []
    tools: list[PostTurnToolReceipt] = []
    receipt_digest = execution_receipt_digest(execution)
    for node in plan.nodes:
        arguments = node.arguments
        function = arguments.get("function_name") if node.kind is QueryNodeKind.FUNCTION else None
        if node.kind is QueryNodeKind.FUNCTION and not isinstance(function, str):
            return {
                **details,
                "post_turn_procedure": {
                    "kind": "unavailable",
                    "reason": "function_identity_absent",
                },
            }
        try:
            argument_shape = _argument_shape(arguments)
        except _ShapeDepthError:
            return {
                **details,
                "post_turn_procedure": {"kind": "unavailable", "reason": "argument_shape_too_deep"},
            }
        shape.append(
            {
                "kind": node.kind.value,
                "function": function,
                "arguments": argument_shape,
                "depends_on": sorted(positions[item] for item in node.depends_on),
                "output_kind": node.output_kind,
            }
        )
        if isinstance(function, str):
            tools.append(
                PostTurnToolReceipt(
                    tool_name=function, status="completed", evidence_ref=receipt_digest
                )
            )
    receipt = PostTurnProcedureReceipt(
        principal_scope=f"sha256:{hashlib.sha256(request.principal.subject_id.encode()).hexdigest()}",
        turn_id=request.turn_id,
        ontology_release_digest=plan.ontology_release_digest,
        semantic_catalog_digest=plan.semantic_catalog_digest,
        plan_digest=plan.plan_digest,
        execution_receipt_digest=receipt_digest,
        shape_digest=content_digest(
            {
                "version": 1,
                "ontology_release_digest": plan.ontology_release_digest,
                "semantic_catalog_digest": plan.semantic_catalog_digest,
                "purpose": plan.purpose,
                "nodes": shape,
                "outputs": [positions[item] for item in plan.output_node_ids],
            }
        ),
        tool_receipts=tuple(tools),
    )
    return {**details, "post_turn_procedure": receipt.model_dump(mode="json")}


def _unavailable_reason(
    request: SemanticTurnRequest, plan: OntologyQueryPlan, execution: QueryPlanExecution
) -> str | None:
    if request.principal.principal_kind is not OperatorPrincipalKind.HUMAN:
        return "human_query_required"
    if execution.plan_digest != plan.plan_digest:
        return "execution_plan_mismatch"
    if (
        execution.status != "completed"
        or execution.output_node_ids != plan.output_node_ids
        or len(execution.receipts) != len(plan.nodes)
        or {receipt.goal_id for receipt in execution.receipts}
        != {node.node_id for node in plan.nodes}
        or any(receipt.status is not TaskStatus.COMPLETED for receipt in execution.receipts)
        or set(execution.results) != {node.node_id for node in plan.nodes}
    ):
        return "complete_execution_required"
    if any(
        isinstance(result.value, QueryTable) and not result.value.complete
        for result in execution.results.values()
    ):
        return "complete_evidence_required"
    return None


def _argument_shape(value: object, *, depth: int = 0) -> object:
    """Retain JSON types and structure, never scalar argument values."""
    if depth > 16:
        raise _ShapeDepthError("post-turn argument shape exceeds the observation depth budget")
    if isinstance(value, Mapping):
        return {key: _argument_shape(item, depth=depth + 1) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_argument_shape(item, depth=depth + 1) for item in value]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise ValueError("post-turn procedure arguments MUST contain JSON values only")
