"""Project verified semantic query receipts into bounded read-only activities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.conversation.semantic_trajectory_presentation import (
    verified_query_command,
)
from fdai_runtime_diagnostics import observe_stage as observe_development_stage
from fdai_service_contracts import MAX_INTENT_GRAPH_GOALS, SemanticQueryProgress

_MAX_EXECUTION_COMMAND_CHARS = 16 * 1024
_MAX_EXECUTION_OUTPUT_CHARS = 64 * 1024


def query_execution_target(capability: str) -> JsonObject:
    """Describe the fixed internal target for one registered query capability."""
    operation = capability.removeprefix("query.").replace(".", "_")
    return {
        "interface_kind": "internal_query",
        "service": "core-control-plane",
        "component": "OntologyQueryPlanExecutor",
        "operation": (
            "object_set_materialization" if capability == "query.object_set" else operation
        ),
        "source_kind": (
            "ontology_instance_store"
            if capability == "query.object_set"
            else "registered_query_handler"
        ),
        "transport": "event_bus",
    }


def verified_query_activities(
    projection: Mapping[str, object],
    *,
    locale: str,
) -> tuple[JsonObject, ...]:
    """Project every exact verified goal and receipt as one readable activity."""
    semantic = projection.get("semantic_result")
    graph = semantic.get("intent_graph") if isinstance(semantic, Mapping) else None
    evidence = semantic.get("intent_graph_evidence") if isinstance(semantic, Mapping) else None
    graph_goals = graph.get("goals") if isinstance(graph, Mapping) else None
    evidence_goals = evidence.get("goals") if isinstance(evidence, Mapping) else None
    if (
        not isinstance(graph_goals, list)
        or not isinstance(evidence_goals, list)
        or not 1 <= len(graph_goals) <= MAX_INTENT_GRAPH_GOALS
        or len(graph_goals) != len(evidence_goals)
    ):
        return ()
    korean = locale.casefold().startswith("ko")
    outputs = technical_outputs_by_node(projection)
    activities: list[JsonObject] = []
    for graph_goal, receipt in zip(graph_goals, evidence_goals, strict=True):
        if not isinstance(graph_goal, Mapping) or not isinstance(receipt, Mapping):
            return ()
        goal_id = graph_goal.get("goal_id")
        intent = graph_goal.get("intent")
        capability = graph_goal.get("capability")
        arguments = graph_goal.get("arguments")
        task_id = receipt.get("task_id")
        status = receipt.get("status")
        duration_ms = receipt.get("duration_ms")
        started_at = receipt.get("started_at")
        completed_at = receipt.get("completed_at")
        evidence_refs = receipt.get("evidence_refs", [])
        depends_on = receipt.get("depends_on", [])
        reason = receipt.get("reason")
        if (
            not isinstance(goal_id, str)
            or receipt.get("goal_id") != goal_id
            or not isinstance(intent, str)
            or receipt.get("intent") != intent
            or not isinstance(capability, str)
            or receipt.get("capability") != capability
            or not isinstance(arguments, Mapping)
            or not isinstance(task_id, str)
            or not task_id.startswith("query:")
            or status
            not in {"completed", "unavailable", "failed", "cancelled", "timed_out", "skipped"}
            or not isinstance(duration_ms, int)
            or isinstance(duration_ms, bool)
            or duration_ms < 0
            or not isinstance(started_at, str)
            or not isinstance(completed_at, str)
            or not isinstance(evidence_refs, list)
            or any(not isinstance(item, str) for item in evidence_refs)
            or not isinstance(depends_on, list)
            or any(not isinstance(item, str) for item in depends_on)
            or (reason is not None and not isinstance(reason, str))
        ):
            return ()
        if not receipt_represents_read(status, reason):
            continue
        observe_development_stage(f"conversation.query.{status}", duration_ms)
        node_id = task_id.removeprefix("query:")
        node_output = outputs.get(node_id)
        command = verified_query_command(
            capability=capability,
            intent=intent,
            graph_goal=graph_goal,
            status=status,
            node_output=node_output,
        )
        if len(command) > _MAX_EXECUTION_COMMAND_CHARS:
            return ()
        output = redacted_activity_output(
            status=status,
            reason=reason,
            evidence_count=len(evidence_refs),
            node_output=node_output,
        )
        output_truncated = isinstance(node_output, Mapping) and (
            node_output.get("display_truncated") is True
            or node_output.get("source_truncation_reason") is not None
        )
        activities.append(
            cast(
                JsonObject,
                {
                    "activity_id": f"semantic:goal:{node_id}",
                    "status": activity_status(status),
                    "label": query_goal_label(node_id, intent=intent, korean=korean),
                    "detail": query_goal_detail(
                        capability=capability,
                        status=status,
                        evidence_count=len(evidence_refs),
                        dependency_count=len(depends_on),
                        reason=reason,
                        korean=korean,
                    ),
                    "observed_at": completed_at,
                    "execution": {
                        "tool": "Ontology query",
                        "input_kind": "query",
                        "target": query_execution_target(capability),
                        "command": command,
                        "redacted": True,
                        "status": status,
                        "output_status": (
                            "available" if node_output is not None else "not_available"
                        ),
                        "output": output,
                        "output_truncated": output_truncated,
                        "started_at": started_at,
                        "completed_at": completed_at,
                        "duration_ms": duration_ms,
                    },
                },
            )
        )
    return tuple(activities)


def progress_query_activity(progress: SemanticQueryProgress, *, locale: str) -> JsonObject:
    """Project one actual Core node update into the stable query activity shape."""
    status = str(progress.status)
    korean = locale.casefold().startswith("ko")
    output: str | None = None
    if status != "running":
        output_value: dict[str, object] = {
            "status": status,
            "duration_ms": progress.duration_ms,
            "evidence_ref_count": len(progress.evidence_refs),
        }
        if progress.reason is not None:
            output_value["reason"] = progress.reason
        output = json.dumps(output_value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return cast(
        JsonObject,
        {
            "activity_id": f"semantic:goal:{progress.node_id}",
            "status": status if status == "running" else activity_status(status),
            "label": query_goal_label(
                progress.node_id,
                intent=progress.node_kind.value,
                korean=korean,
            ),
            "detail": query_goal_detail(
                capability=progress.capability,
                status=status,
                evidence_count=len(progress.evidence_refs),
                dependency_count=len(progress.depends_on),
                reason=progress.reason,
                korean=korean,
            ),
            "observed_at": (progress.completed_at or progress.started_at).isoformat(),
            "completed": progress.step_index - (1 if status == "running" else 0),
            "total": progress.step_total,
            "execution": {
                "tool": "Ontology query",
                "input_kind": "query",
                "target": query_execution_target(progress.capability),
                "command": progress.capability,
                "redacted": True,
                "status": status,
                "output_status": "not_available",
                **({"output": output} if output is not None else {}),
                "output_truncated": False,
                "started_at": progress.started_at.isoformat(),
                **(
                    {
                        "completed_at": progress.completed_at.isoformat(),
                        "duration_ms": progress.duration_ms,
                    }
                    if progress.completed_at is not None
                    else {}
                ),
            },
        },
    )


def redacted_activity_output(
    *,
    status: str,
    reason: object,
    evidence_count: int,
    node_output: Mapping[str, object] | None,
) -> str:
    """Summarize one receipt without exposing provider input or result values."""
    summary: dict[str, object] = {"status": status, "evidence_ref_count": evidence_count}
    if isinstance(reason, str):
        summary["reason"] = reason
    if node_output is not None:
        for field in (
            "returned_rows",
            "total_rows",
            "source_complete",
            "source_truncation_reason",
            "display_truncated",
        ):
            value = node_output.get(field)
            if field in node_output and (isinstance(value, bool | int | str) or value is None):
                summary[field] = value
    encoded = json.dumps(summary, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if len(encoded) > _MAX_EXECUTION_OUTPUT_CHARS:
        raise ValueError("semantic execution summary exceeds its bound")
    return encoded


def technical_outputs_by_node(
    projection: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    """Index bounded technical outputs by their semantic node id."""
    payload = projection.get("payload")
    details = payload.get("technical_details") if isinstance(payload, Mapping) else None
    outputs = details.get("outputs") if isinstance(details, Mapping) else None
    if not isinstance(outputs, list):
        return {}
    return {
        node_id: output
        for output in outputs
        if isinstance(output, Mapping) and isinstance((node_id := output.get("node_id")), str)
    }


def activity_status(status: object) -> str:
    """Map query receipt state to the stable activity state."""
    if status == "completed":
        return "completed"
    if status in {"unavailable", "skipped"}:
        return "unavailable"
    return "failed"


def receipt_represents_read(status: str, reason: object) -> bool:
    """Exclude receipts that never executed a query read."""
    return status not in {"cancelled", "skipped"} and reason != "capability_unavailable"


def query_goal_label(node_id: str, *, intent: str, korean: bool) -> str:
    """Render one stable localized semantic query activity label."""
    readable = node_id.replace("_", " ").replace("-", " ")
    if korean:
        labels = {
            "resolve-target": "정확한 대상 리소스 확인",
            "change-activity": "Activity Log의 변경 및 배포 이력 조회",
            "symptom-baseline": "기준 구간 지연 메트릭 조회",
            "symptom-current": "현재 구간 지연 메트릭 조회",
            "symptom-change": "기준 구간과 현재 구간의 증상 변화 비교",
            "topology-before": "변화 전 토폴로지 스냅샷 조회",
            "topology-after": "변화 후 토폴로지 스냅샷 조회",
            "topology-change": "변화 전후 토폴로지 차이 계산",
        }
        if node_id in labels:
            return labels[node_id]
        if node_id.startswith("expand-"):
            return "의존성 및 토폴로지 경로 확인"
        if node_id.startswith("cause-"):
            return f"원인 후보 메트릭 조회: {readable.removeprefix('cause ')}"
        if node_id.startswith("hypothesis-"):
            return f"경쟁 원인 가설 평가: {readable.removeprefix('hypothesis ')}"
        return f"검증된 의미 조회 실행: {intent.replace('_', ' ')}"
    labels = {
        "resolve-target": "Resolve the exact target resource",
        "change-activity": "Read change and deployment history from Activity Log",
        "symptom-baseline": "Read the baseline latency window",
        "symptom-current": "Read the current latency window",
        "symptom-change": "Compare symptom change across the two windows",
        "topology-before": "Read the topology snapshot before the change",
        "topology-after": "Read the topology snapshot after the change",
        "topology-change": "Calculate the before-and-after topology difference",
    }
    if node_id in labels:
        return labels[node_id]
    if node_id.startswith("expand-"):
        return "Trace dependency and topology paths"
    if node_id.startswith("cause-"):
        return f"Read candidate cause metrics: {readable.removeprefix('cause ')}"
    if node_id.startswith("hypothesis-"):
        return f"Evaluate competing cause hypothesis: {readable.removeprefix('hypothesis ')}"
    return f"Run verified semantic query: {intent.replace('_', ' ')}"


def query_goal_detail(
    *,
    capability: str,
    status: str,
    evidence_count: int,
    dependency_count: int,
    reason: str | None,
    korean: bool,
) -> str:
    """Render bounded localized detail for one query receipt."""
    if korean:
        detail = (
            f"{capability} - {status} - 근거 참조 {evidence_count}개 - "
            f"선행 단계 {dependency_count}개"
        )
        return f"{detail} - 제한: {reason}" if reason is not None else detail
    evidence_label = "reference" if evidence_count == 1 else "references"
    dependency_label = "prerequisite" if dependency_count == 1 else "prerequisites"
    detail = (
        f"{capability} - {status} - {evidence_count} evidence {evidence_label} - "
        f"{dependency_count} {dependency_label}"
    )
    return f"{detail} - limitation: {reason}" if reason is not None else detail
