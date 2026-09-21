"""Render content-redacted technical trajectories for verified semantic reads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject

_MAX_EXECUTION_COMMAND_CHARS = 16 * 1024
_MAX_EXECUTION_OUTPUT_CHARS = 2_048


def semantic_technical_trajectory(
    *,
    projection: Mapping[str, object],
    technical_details: object,
    checks_completed: int,
    checks_total: int,
    locale: str,
) -> JsonObject | None:
    """Project only receipt-backed read attempts with content-redacted execution detail."""
    semantic = projection.get("semantic_result")
    if not isinstance(semantic, Mapping):
        return None
    graph = semantic.get("intent_graph")
    evidence = semantic.get("intent_graph_evidence")
    graph_goals = graph.get("goals") if isinstance(graph, Mapping) else None
    evidence_goals = evidence.get("goals") if isinstance(evidence, Mapping) else None
    if (
        not isinstance(graph, Mapping)
        or graph.get("schema_version") != 2
        or not isinstance(evidence, Mapping)
        or evidence.get("schema_version") not in {1, 2}
        or not isinstance(graph_goals, list)
        or not isinstance(evidence_goals, list)
        or not graph_goals
        or len(graph_goals) != len(evidence_goals)
    ):
        return None
    outputs = technical_details.get("outputs") if isinstance(technical_details, Mapping) else None
    outputs_by_node = (
        {
            node_id: output
            for output in outputs
            if isinstance(output, Mapping) and isinstance((node_id := output.get("node_id")), str)
        }
        if isinstance(outputs, list)
        else {}
    )
    activities: list[JsonObject] = []
    truncated_outputs = 0
    korean = locale.casefold().startswith("ko")
    for graph_goal, receipt in zip(graph_goals, evidence_goals, strict=True):
        if not isinstance(graph_goal, Mapping) or not isinstance(receipt, Mapping):
            return None
        goal_id = graph_goal.get("goal_id")
        intent = graph_goal.get("intent")
        capability = graph_goal.get("capability")
        task_id = receipt.get("task_id")
        status = receipt.get("status")
        duration_ms = receipt.get("duration_ms")
        started_at = receipt.get("started_at")
        completed_at = receipt.get("completed_at")
        reason = receipt.get("reason")
        refs = receipt.get("evidence_refs", [])
        if (
            not isinstance(goal_id, str)
            or receipt.get("goal_id") != goal_id
            or not isinstance(intent, str)
            or receipt.get("intent") != intent
            or not isinstance(capability, str)
            or receipt.get("capability") != capability
            or not isinstance(task_id, str)
            or not task_id.startswith("query:")
            or status
            not in {"completed", "unavailable", "failed", "cancelled", "timed_out", "skipped"}
            or not isinstance(duration_ms, int)
            or isinstance(duration_ms, bool)
            or duration_ms < 0
            or not isinstance(started_at, str)
            or not isinstance(completed_at, str)
            or not isinstance(refs, list)
            or any(not isinstance(item, str) or not item for item in refs)
            or (reason is not None and not isinstance(reason, str))
        ):
            return None
        if not receipt_represents_read(status, reason):
            continue
        node_id = task_id.removeprefix("query:")
        node_output = outputs_by_node.get(node_id)
        output_truncated = isinstance(node_output, Mapping) and (
            node_output.get("display_truncated") is True
            or node_output.get("source_truncation_reason") is not None
        )
        truncated_outputs += int(output_truncated)
        output = redacted_execution_output(
            status=status,
            reason=reason,
            evidence_count=len(refs),
            node_output=node_output,
        )
        command = verified_query_command(
            capability=capability,
            intent=intent,
            graph_goal=graph_goal,
            status=status,
            node_output=node_output,
        )
        activities.append(
            cast(
                JsonObject,
                {
                    "activity_id": f"semantic:goal:{node_id}",
                    "kind": "read.execution",
                    "status": trajectory_status(status),
                    "label": (
                        f"읽기 전용 조회: {capability}"
                        if korean
                        else f"Read-only query: {capability}"
                    ),
                    "detail": (
                        f"상태 {status}, 근거 참조 {len(refs)}개"
                        if korean
                        else f"Status {status}; {len(refs)} evidence references"
                    ),
                    "authority": receipt.get("authority") or "read_only",
                    "source": receipt.get("authority") or "registered_query_handler",
                    "observed_at": completed_at,
                    "evidence_refs": refs,
                    "execution": {
                        "tool": "Ontology query",
                        "input_kind": "query",
                        "command": command,
                        "target": semantic_query_target(capability),
                        "redacted": True,
                        "status": status,
                        "duration_ms": duration_ms,
                        "started_at": started_at,
                        "completed_at": completed_at,
                        "output_status": (
                            "available" if node_output is not None else "not_available"
                        ),
                        "output": output,
                        "output_truncated": output_truncated,
                    },
                },
            )
        )
    if not activities:
        return None
    return cast(
        JsonObject,
        {
            "schema_version": 1,
            "activities": activities,
            "branches": [],
            "milestones": [],
            "omitted": {"activities": 0, "branches": 0, "milestones": 0},
            "checks_completed": checks_completed,
            "checks_total": checks_total,
            "truncated_outputs": truncated_outputs,
        },
    )


def verified_query_command(
    *,
    capability: str,
    intent: str,
    graph_goal: Mapping[str, object],
    status: str,
    node_output: Mapping[str, object] | None,
) -> str:
    """Expose a bounded ObjectSet only when goal, receipt, and output evidence agree."""
    if (
        capability != "query.object_set"
        or intent != "object_set"
        or status != "completed"
        or node_output is None
    ):
        return capability
    returned_rows = node_output.get("returned_rows")
    total_rows = node_output.get("total_rows")
    if (
        not isinstance(returned_rows, int)
        or isinstance(returned_rows, bool)
        or returned_rows < 0
        or not isinstance(total_rows, int)
        or isinstance(total_rows, bool)
        or total_rows < returned_rows
    ):
        return capability
    return object_set_query_command(
        capability=capability,
        intent=intent,
        arguments=graph_goal.get("arguments"),
    )


def object_set_query_command(*, capability: str, intent: str, arguments: object) -> str:
    """Render one exact bounded ObjectSet definition without adding authority."""
    if (
        capability != "query.object_set"
        or intent != "object_set"
        or not isinstance(arguments, dict)
        or set(arguments) != {"definition"}
        or not isinstance((definition := arguments.get("definition")), dict)
    ):
        return capability
    encoded = json.dumps(
        {
            "capability": capability,
            "execution_authority": False,
            "object_set": definition,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return encoded if len(encoded) <= _MAX_EXECUTION_COMMAND_CHARS else capability


def redacted_execution_output(
    *,
    status: str,
    reason: object,
    evidence_count: int,
    node_output: Mapping[str, object] | None,
) -> str:
    """Serialize only bounded execution status and count metadata."""
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
    if len(encoded) > _MAX_EXECUTION_OUTPUT_CHARS:  # pragma: no cover - fixed fields stay bounded
        raise ValueError("semantic execution summary exceeds its bound")
    return encoded


def semantic_query_target(capability: str) -> JsonObject:
    """Describe the fixed internal read-only query target."""
    return cast(
        JsonObject,
        {
            "interface_kind": "internal_query",
            "service": "core-control-plane",
            "component": "OntologyQueryPlanExecutor",
            "operation": capability.removeprefix("query.").replace(".", "_"),
            "source_kind": "registered_query_handler",
            "transport": "event_bus",
        },
    )


def trajectory_status(status: str) -> str:
    """Map query receipt state to presentation trajectory state."""
    if status == "completed":
        return "completed"
    if status in {"unavailable", "skipped"}:
        return "unavailable"
    return "failed"


def receipt_represents_read(status: str, reason: object) -> bool:
    """Exclude receipts that never executed a read."""
    return status not in {"cancelled", "skipped"} and reason != "capability_unavailable"
