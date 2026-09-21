"""Receipt-bound, non-exhaustive presentation of authorized instance candidates."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.semantic_runtime import SemanticTurnResult
from fdai.core.ontology_platform.instance_candidate_queries import INSTANCE_CANDIDATES_FUNCTION_NAME
from fdai.core.ontology_platform.query_execution import QueryPlanExecution
from fdai_service_contracts.ontology_query import QueryNodeKind, TaskStatus, content_digest
from fdai_service_contracts.semantic_turn import SemanticTurnRequest

from .semantic_turn_request import principal


def project_instance_candidates(
    request: SemanticTurnRequest,
    result: SemanticTurnResult,
    execution: QueryPlanExecution,
) -> tuple[bool, dict[str, object] | None]:
    plan = result.planning.plan
    if plan is None:
        return False, None
    nodes = tuple(
        node
        for node in getattr(plan, "nodes", ())
        if isinstance(getattr(node, "arguments", None), Mapping)
        and node.arguments.get("function_name") == INSTANCE_CANDIDATES_FUNCTION_NAME
    )
    if not nodes:
        return False, None
    if len(nodes) != 1 or execution.output_node_ids != (nodes[0].node_id,):
        return True, None
    node = nodes[0]
    node_result = execution.results.get(node.node_id)
    arguments = node.arguments.get("arguments")
    receipts = tuple(
        receipt for receipt in execution.receipts if receipt.task_id == f"query:{node.node_id}"
    )
    if (
        node.kind is not QueryNodeKind.FUNCTION
        or node_result is None
        or not isinstance(arguments, dict)
        or set(arguments) != {"query", "limit"}
        or not isinstance(arguments["query"], str)
        or type(arguments["limit"]) is not int
        or not 1 <= arguments["limit"] <= 20
        or len(receipts) != 1
        or receipts[0].status is not TaskStatus.COMPLETED
        or receipts[0].goal_id != node.node_id
        or receipts[0].intent != "function"
        or receipts[0].capability != "query.function"
        or receipts[0].evidence_refs != node_result.evidence_refs
        or not node_result.evidence_refs
        or not isinstance(node_result.value, dict)
    ):
        return True, None
    value = node_result.value
    candidates, count, references = (
        value.get("candidates"),
        value.get("candidate_count"),
        value.get("evidence_refs"),
    )
    if (
        value.get("authority") != "candidate_only"
        or value.get("execution_authority") is not False
        or value.get("exhaustive") is not False
        or request.purpose != "operations-review"
        or value.get("ontology_release_digest") != plan.ontology_release_digest
        or value.get("principal_scope_digest")
        != semantic_principal_scope_digest(principal=principal(request), purpose=request.purpose)
        or value.get("query_digest") != content_digest(arguments)
        or value.get("result_digest")
        != content_digest({key: item for key, item in value.items() if key != "result_digest"})
        or not isinstance(candidates, list)
        or type(count) is not int
        or not 0 <= count <= 20_000
        or len(candidates) != min(count, arguments["limit"])
        or value.get("truncated") is not (count > len(candidates))
        or not isinstance(references, list)
        or len(references) > 16
        or any(not isinstance(ref, str) or not ref.startswith("sha256:") for ref in references)
        or (candidates and not references)
    ):
        return True, None
    identities: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != {
            "id",
            "object_type",
            "properties",
            "revision",
        }:
            return True, None
        identifier, object_type, revision = (
            candidate["id"],
            candidate["object_type"],
            candidate["revision"],
        )
        if (
            not isinstance(identifier, str)
            or not 1 <= len(identifier) <= 4096
            or not isinstance(object_type, str)
            or not 1 <= len(object_type) <= 256
            or type(revision) is not int
            or revision < 0
            or not isinstance(candidate["properties"], Mapping)
            or (object_type, identifier) in seen
        ):
            return True, None
        seen.add((object_type, identifier))
        identities.append({"id": identifier, "object_type": object_type, "revision": revision})
    return True, {
        "node_id": node.node_id,
        "instance_candidates": identities,
        "candidate_count": count,
        "source_result_digest": value["result_digest"],
        "source_truncated": value["truncated"],
        "exhaustive": False,
        "execution_authority": False,
        "evidence_refs": list(node_result.evidence_refs),
    }


def render_instance_candidates(locale: str, output: Mapping[str, object]) -> str:
    korean = locale.casefold().startswith("ko")
    candidates = output["instance_candidates"]
    if not isinstance(candidates, list):
        raise ValueError("instance candidate projection is malformed")
    lines = ["## 인스턴스 후보" if korean else "## Instance candidates", ""]
    lines.append(
        "현재 접근 권한을 확인한 후보입니다. 전체 목록이 아니며 빈 결과도 부재를 입증하지 않습니다."
        if korean
        else "These candidates passed current access checks. This is not an exhaustive list; "
        "an empty result does not prove absence."
    )
    lines.append("")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("instance candidate identity is malformed")
        label = (
            f"{candidate['object_type']}: {candidate['id']}".replace("`", "'")
            .replace("\n", " ")
            .replace("\r", " ")
        )
        lines.append(f"- `{label}`")
    if not candidates:
        lines.append("- 반환된 후보가 없습니다." if korean else "- No candidates were returned.")
    if output["source_truncated"]:
        lines.append(
            "- 후보 상한으로 결과가 제한되었습니다."
            if korean
            else "- Results were limited by the candidate bound."
        )
    lines.extend(
        ["", "실행 권한은 부여되지 않습니다." if korean else "No execution authority is granted."]
    )
    return "\n".join(lines)
