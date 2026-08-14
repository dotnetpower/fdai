"""Validate and render exact-release ontology relationship query results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.ontology_platform import QueryPlanExecution


def project_ontology_relationships(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> tuple[bool, dict[str, object] | None, str | None]:
    """Return one verified relationship output or fail closed on any drift."""

    plan = result.planning.plan
    if plan is None:
        return True, None, None
    relationship_nodes: list[tuple[object, dict[str, Any]]] = []
    for node in getattr(plan, "nodes", ()):
        if getattr(node, "node_id", None) not in execution.output_node_ids:
            continue
        try:
            arguments = node.arguments
        except Exception:  # noqa: BLE001, S112 - malformed plan output fails closed
            continue
        if isinstance(arguments, dict) and arguments.get("function_name") == (
            "query.ontology_relationships"
        ):
            relationship_nodes.append((node, arguments))
    if not relationship_nodes:
        return False, None, None
    if len(relationship_nodes) != 1:
        return True, None, None
    node, node_arguments = relationship_nodes[0]
    node_id = getattr(node, "node_id", None)
    query_arguments = node_arguments.get("arguments")
    node_result = execution.results.get(node_id) if isinstance(node_id, str) else None
    node_kind = getattr(getattr(node, "kind", None), "value", None)
    receipts = tuple(
        receipt for receipt in execution.receipts if receipt.task_id == f"query:{node_id}"
    )
    if (
        not isinstance(node_id, str)
        or not isinstance(query_arguments, dict)
        or node_result is None
        or node_kind != "function"
        or len(receipts) != 1
        or receipts[0].goal_id != node_id
        or receipts[0].intent != "function"
        or receipts[0].capability != "query.function"
        or receipts[0].evidence_refs != node_result.evidence_refs
    ):
        return True, None, None
    value = node_result.value
    requested = query_arguments.get("object_types")
    limit = query_arguments.get("limit")
    if (
        not isinstance(value, dict)
        or not isinstance(requested, list)
        or not 1 <= len(requested) <= 2
        or len(requested) != len(set(requested))
        or any(not isinstance(item, str) or not item for item in requested)
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
        or value.get("object_types") != requested
        or value.get("authority") != "ontology_release"
        or value.get("ontology_release_digest") != plan.ontology_release_digest
        or value.get("execution_authority") is not False
        or not isinstance(value.get("complete"), bool)
    ):
        return True, None, None
    relationships = value.get("relationships")
    if not isinstance(relationships, list) or len(relationships) > limit:
        return True, None, None
    requested_set = set(requested)
    link_names: set[str] = set()
    for relationship in relationships:
        if not isinstance(relationship, dict) or set(relationship) != {
            "link_type",
            "from_type",
            "to_type",
            "cardinality",
            "description",
        }:
            return True, None, None
        link_type = relationship.get("link_type")
        from_type = relationship.get("from_type")
        to_type = relationship.get("to_type")
        if (
            not isinstance(link_type, str)
            or not link_type
            or link_type in link_names
            or not isinstance(from_type, str)
            or not isinstance(to_type, str)
            or not isinstance(relationship.get("cardinality"), str)
            or not isinstance(relationship.get("description"), str)
        ):
            return True, None, None
        endpoints = {from_type, to_type}
        endpoint_matches = (
            endpoints <= requested_set
            if len(requested_set) == 2
            else not endpoints.isdisjoint(requested_set)
        )
        if not endpoint_matches:
            return True, None, None
        link_names.add(link_type)
    return True, value, node_id


def render_ontology_relationship_answer(
    locale: str,
    output: Mapping[str, object],
) -> str:
    """Render one bounded relationship explanation in the operator locale."""

    projection = output.get("ontology_relationships")
    if not isinstance(projection, Mapping):  # pragma: no cover - projection invariant
        raise RuntimeError("ontology relationship projection is invalid")
    object_types = projection.get("object_types")
    relationships = projection.get("relationships")
    complete = projection.get("complete")
    if not isinstance(object_types, list) or not isinstance(relationships, list):
        raise RuntimeError("ontology relationship output is invalid")
    korean = locale.casefold().startswith("ko")
    title = "## 온톨로지 관계" if korean else "## Ontology relationships"
    lines = [title, ""]
    if relationships:
        for item in relationships:
            if not isinstance(item, Mapping):  # pragma: no cover - projection invariant
                raise RuntimeError("ontology relationship row is invalid")
            link = str(item["link_type"])
            source = str(item["from_type"])
            target = str(item["to_type"])
            cardinality = str(item["cardinality"])
            description = str(item["description"])
            lines.append(f"- `{source}` --`{link}`--> `{target}` (`{cardinality}`): {description}")
    else:
        names = ", ".join(f"`{item}`" for item in object_types)
        lines.append(
            f"- 활성 온톨로지 릴리스에서 {names}를 연결하는 LinkType이 없습니다."
            if korean
            else f"- No LinkType in the active ontology release connects {names}."
        )
    if complete is False:
        lines.extend(
            [
                "",
                (
                    "결과가 제한에 도달했으므로 추가 관계는 알 수 없습니다."
                    if korean
                    else "The result reached its limit, so additional relationships are unknown."
                ),
            ]
        )
    lines.extend(
        [
            "",
            (
                "이 설명은 활성 릴리스의 정확한 LinkType 선언에서 가져온 읽기 전용 의미이며 "
                "실행 권한을 부여하지 않습니다."
                if korean
                else (
                    "This explanation is read-only meaning from the exact LinkType declaration "
                    "in the active release and grants no execution authority."
                )
            ),
        ]
    )
    return "\n".join(lines)


__all__ = ["project_ontology_relationships", "render_ontology_relationship_answer"]
