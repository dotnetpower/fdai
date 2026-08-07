"""Pure progress projections for server-owned chat tool evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.delivery.operator_api.projections.conversation.inventory import (
    inventory_execution_query,
)
from fdai.delivery.operator_api.routes.chat_execution_output import inventory_execution_output
from fdai.delivery.operator_api.routes.inventory_provider_execution import (
    project_inventory_provider_execution,
)


def _tool_execution_progress_event(
    evidence: Mapping[str, Any],
    *,
    started_at: datetime,
    duration_ms: int,
) -> dict[str, object] | None:
    tool = evidence.get("tool")
    queries = {
        "query_llm_usage": {
            "operation": "query_llm_usage",
            "arguments": evidence.get("analysis_context"),
        },
        "query_subscription_health": {
            "operation": "query_subscription_health",
            "scope": "server-owned",
        },
        "query_t2_recovery": {
            "operation": "query_t2_recovery",
            "scope": "server-owned",
        },
    }
    labels = {
        "query_inventory": "Applied inventory query",
        "query_llm_usage": "Read measured LLM usage",
        "query_subscription_health": "Checked subscription health",
        "query_t2_recovery": "Read T2 recovery state",
    }
    if not isinstance(tool, str) or (tool not in queries and tool != "query_inventory"):
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    result_status = str(result.get("status") or "unavailable")
    completed = result_status in {"matched", "partial", "none", "ambiguous"}
    summary: dict[str, object] = {"status": result_status}
    for key in (
        "matched_count",
        "total_resources",
        "resource_count",
        "metric_checked",
        "metric_unavailable",
    ):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            summary[key] = value
    if tool == "query_subscription_health":
        for key in ("source", "observed_at"):
            value = result.get(key)
            if isinstance(value, str) and value:
                summary[key] = value[:200]
        findings = result.get("findings")
        if isinstance(findings, list):
            summary["finding_count"] = min(len(findings), 20)
        if result.get("truncated") is True:
            summary["truncated"] = True
    output, output_truncated = (
        inventory_execution_output(result)
        if tool == "query_inventory"
        else (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), False)
    )
    completed_at = datetime.now(UTC)
    execution: dict[str, object] = {
        "tool": "FDAI IQL" if tool == "query_inventory" else "FDAI server read",
        "command": (
            inventory_execution_query(evidence)
            if tool == "query_inventory"
            else json.dumps(queries[tool], indent=2, sort_keys=True)
        ),
        "input_kind": "query",
        "redacted": True,
        "output": output,
        "exit_code": None,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_ms": duration_ms,
    }
    if output_truncated:
        execution["output_truncated"] = True
    event: dict[str, object] = {
        "event": "activity",
        "activity_id": f"{tool}-execution",
        "kind": "read.execution",
        "status": "completed" if completed else "unavailable",
        "label": labels[tool],
        "detail": _tool_execution_detail(summary),
        "completed": 1 if completed else 0,
        "total": 1,
        "authority": str(evidence.get("authority") or "server_read_model"),
        "observed_at": completed_at.isoformat(),
        "execution": execution,
    }
    return event


def _tool_execution_progress_events(
    evidence: Mapping[str, Any],
    *,
    started_at: datetime,
    duration_ms: int,
) -> tuple[dict[str, object], ...]:
    primary = _tool_execution_progress_event(
        evidence,
        started_at=started_at,
        duration_ms=duration_ms,
    )
    if primary is None:
        return ()
    if evidence.get("tool") != "query_inventory":
        return (primary,)
    return (primary, *_inventory_provider_progress_events(evidence))


def _inventory_provider_progress_events(
    evidence: Mapping[str, Any],
) -> tuple[dict[str, object], ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    provider = project_inventory_provider_execution(result.get("provider_execution"))
    if provider is None:
        return ()
    snapshot_at = str(result.get("snapshot_at") or "snapshot time unavailable")
    backend = str(provider["backend"])
    subscription_id = provider.get("subscription_id")
    events: list[dict[str, object]] = []
    for index, command in enumerate(provider["commands"]):
        label = str(command["label"])
        is_arg = label == "resources" and backend == "azure_resource_graph"
        events.append(
            {
                "event": "activity",
                "activity_id": f"query_inventory-provider-{index}",
                "kind": "read.provider",
                "status": "completed",
                "label": (
                    "Listed Azure resource groups"
                    if label == "resource_groups"
                    else "Queried Azure Resource Graph"
                    if is_arg
                    else "Listed Azure resources"
                ),
                "detail": (
                    f"Subscription {subscription_id} - snapshot source observed at {snapshot_at}"
                    if isinstance(subscription_id, str)
                    else f"Snapshot source observed at {snapshot_at}"
                ),
                "completed": 1,
                "total": 1,
                "authority": backend,
                "observed_at": snapshot_at,
                "execution": {
                    "tool": "Azure Resource Graph via Azure CLI" if is_arg else "Azure CLI",
                    "command": str(command["command"]),
                    "input_kind": "command",
                    "redacted": True,
                    **(
                        {"duration_ms": command["duration_ms"]}
                        if isinstance(command.get("duration_ms"), int)
                        else {}
                    ),
                    **(
                        {
                            "output": json.dumps(command["result"], ensure_ascii=False, indent=2),
                            **(
                                {"output_truncated": True}
                                if command["result"].get("truncated") is True
                                else {}
                            ),
                        }
                        if isinstance(command.get("result"), Mapping)
                        else {}
                    ),
                },
            }
        )
    return tuple(events)


def _tool_execution_detail(summary: Mapping[str, object]) -> str:
    for key, singular, plural in (
        ("matched_count", "matching resource", "matching resources"),
        ("resource_count", "resource", "resources"),
        ("total_resources", "resource inspected", "resources inspected"),
        ("metric_checked", "metric checked", "metrics checked"),
    ):
        value = summary.get(key)
        if isinstance(value, int):
            return f"{value} {singular if value == 1 else plural}"
    return f"Status: {str(summary.get('status') or 'unavailable').replace('_', ' ')}"
