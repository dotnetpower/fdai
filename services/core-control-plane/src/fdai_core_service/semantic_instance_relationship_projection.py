"""Validate and render secured instance relationship query results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.ontology_platform import QueryPlanExecution

_FUNCTION_NAME = "query.instance_relationships"


def project_instance_relationships(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> tuple[bool, dict[str, object] | None, str | None]:
    """Return one verified instance relationship output or fail closed."""

    plan = result.planning.plan
    if plan is None:
        return True, None, None
    candidates: list[tuple[object, dict[str, Any]]] = []
    for node in getattr(plan, "nodes", ()):
        if getattr(node, "node_id", None) not in execution.output_node_ids:
            continue
        arguments = getattr(node, "arguments", None)
        if isinstance(arguments, dict) and arguments.get("function_name") == _FUNCTION_NAME:
            candidates.append((node, arguments))
    if not candidates:
        return False, None, None
    if len(candidates) != 1:
        return True, None, None

    node, node_arguments = candidates[0]
    node_id = getattr(node, "node_id", None)
    query_arguments = node_arguments.get("arguments")
    dependency_arguments = node_arguments.get("dependency_arguments")
    node_result = execution.results.get(node_id) if isinstance(node_id, str) else None
    receipts = tuple(
        receipt for receipt in execution.receipts if receipt.task_id == f"query:{node_id}"
    )
    if (
        not isinstance(node_id, str)
        or not isinstance(query_arguments, dict)
        or not isinstance(dependency_arguments, dict)
        or set(dependency_arguments.values()) != {"query_result"}
        or node_result is None
        or getattr(getattr(node, "kind", None), "value", None) != "function"
        or len(receipts) != 1
        or receipts[0].goal_id != node_id
        or receipts[0].intent != "function"
        or receipts[0].capability != "query.function"
        or receipts[0].evidence_refs != node_result.evidence_refs
    ):
        return True, None, None

    value = node_result.value
    requested = query_arguments.get("link_types")
    limit = query_arguments.get("limit")
    if (
        not isinstance(value, dict)
        or not isinstance(requested, list)
        or not 1 <= len(requested) <= 64
        or len(requested) != len(set(requested))
        or any(not isinstance(item, str) or not item for item in requested)
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
        or value.get("link_types") != requested
        or not isinstance(value.get("complete"), bool)
        or value.get("execution_authority") is not False
    ):
        return True, None, None
    release = value.get("ontology_release")
    query_result_digest = value.get("query_result_digest")
    if (
        not isinstance(release, dict)
        or release.get("digest") != plan.ontology_release_digest
        or not isinstance(query_result_digest, str)
        or f"ontology-object-set:{query_result_digest}" not in node_result.evidence_refs
    ):
        return True, None, None

    truncation_reasons = value.get("truncation_reasons")
    relationships = value.get("relationships")
    if (
        not isinstance(truncation_reasons, list)
        or any(not isinstance(item, str) or not item for item in truncation_reasons)
        or value["complete"] == bool(truncation_reasons)
        or not isinstance(relationships, list)
        or len(relationships) > limit
    ):
        return True, None, None
    seen: set[tuple[str, str, str]] = set()
    for relationship in relationships:
        if not isinstance(relationship, dict) or set(relationship) != {
            "link_type",
            "from_id",
            "from_type",
            "to_id",
            "to_type",
        }:
            return True, None, None
        values = tuple(relationship.values())
        if any(not isinstance(item, str) or not item for item in values):
            return True, None, None
        key = (
            relationship["from_id"],
            relationship["link_type"],
            relationship["to_id"],
        )
        if relationship["link_type"] not in requested or key in seen:
            return True, None, None
        seen.add(key)
    return True, value, node_id


def render_instance_relationship_answer(
    locale: str,
    output: Mapping[str, object],
) -> str:
    """Render bounded current relationship evidence in the operator locale."""

    projection = output.get("instance_relationships")
    if not isinstance(projection, Mapping):
        raise RuntimeError("instance relationship projection is invalid")
    link_types = projection.get("link_types")
    relationships = projection.get("relationships")
    complete = projection.get("complete")
    if not isinstance(link_types, list) or not isinstance(relationships, list):
        raise RuntimeError("instance relationship output is invalid")

    korean = locale.casefold().startswith("ko")
    lines = ["## 현재 온톨로지 관계" if korean else "## Current ontology relationships", ""]
    if relationships:
        for item in relationships:
            if not isinstance(item, Mapping):
                raise RuntimeError("instance relationship row is invalid")
            lines.append(
                f"- `{item['from_type']}` `{item['from_id']}` "
                f"--`{item['link_type']}`--> `{item['to_type']}` `{item['to_id']}`"
            )
    else:
        names = ", ".join(f"`{item}`" for item in link_types)
        if complete is True:
            lines.append(
                f"- 현재의 완전한 조회 범위에는 {names} 관계가 없습니다."
                if korean
                else f"- No {names} relationships exist in the complete current query scope."
            )
        else:
            lines.append(
                f"- 현재 조회에서 {names} 관계를 찾지 못했지만 조회 범위가 불완전합니다."
                if korean
                else (
                    f"- No {names} relationships were found, but the current query scope "
                    "is incomplete."
                )
            )
    if complete is not True:
        lines.extend(
            [
                "",
                (
                    "조회가 제한되어 추가 관계 또는 관계 부재를 확인할 수 없습니다."
                    if korean
                    else (
                        "The query was bounded, so additional relationships or their absence "
                        "cannot be verified."
                    )
                ),
            ]
        )
    lines.extend(
        [
            "",
            (
                "이 결과는 현재의 증적 결합 읽기 전용 스냅샷이며 실행 권한을 부여하지 않습니다."
                if korean
                else (
                    "This result is a receipt-bound read-only current snapshot and grants no "
                    "execution authority."
                )
            ),
        ]
    )
    return "\n".join(lines)


__all__ = ["project_instance_relationships", "render_instance_relationship_answer"]
