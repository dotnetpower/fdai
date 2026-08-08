"""Serialization helpers for PostgreSQL read-investigation run records."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final

from fdai.core.read_investigation.idempotency import (
    ReadInvestigationRunLease,
    ReadInvestigationRunMode,
    ReadInvestigationRunRecord,
    ReadInvestigationRunState,
    ReadInvestigationRunUsage,
)
from fdai.core.read_investigation.models import (
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationRequest,
    ReadInvestigationResult,
)
from fdai.shared.providers.read_investigation import (
    ActorKind,
    EvidenceFreshness,
    EvidenceLimitationKind,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationIntent,
    ReadToolId,
    ResolvedResource,
    ResourceCandidate,
    ResourceResolution,
    ResourceResolutionStatus,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

COLUMNS: Final[str] = (
    "owner_principal_id, idempotency_key, request_digest, request, mode, state, revision, "
    "attempt_count, "
    "lease_owner, lease_token, lease_expires_at, result, usage, failure_reason, "
    "created_at, updated_at, retention_until, terminal_at"
)


def run_from_row(row: dict[str, Any]) -> ReadInvestigationRunRecord:
    request = _request(_mapping(row["request"]))
    usage_raw = row["usage"]
    result_raw = row["result"]
    lease_owner = row["lease_owner"]
    return ReadInvestigationRunRecord(
        owner_principal_id=str(row["owner_principal_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_digest=str(row["request_digest"]),
        request=request,
        mode=ReadInvestigationRunMode(str(row["mode"])),
        state=ReadInvestigationRunState(str(row["state"])),
        revision=int(row["revision"]),
        attempt_count=int(row["attempt_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retention_until=row["retention_until"],
        terminal_at=row["terminal_at"],
        lease=(
            ReadInvestigationRunLease(
                owner=str(lease_owner),
                token=str(row["lease_token"]),
                expires_at=row["lease_expires_at"],
            )
            if lease_owner is not None
            else None
        ),
        result=_result(_mapping(result_raw), request=request) if result_raw is not None else None,
        usage=_usage(_mapping(usage_raw)) if usage_raw is not None else None,
        failure_reason=str(row["failure_reason"]) if row["failure_reason"] is not None else None,
    )


def request_to_dict(request: ReadInvestigationRequest) -> dict[str, object]:
    return {
        "requester_ref": request.requester_ref,
        "conversation_ref": request.conversation_ref,
        "correlation_ref": request.correlation_ref,
        "intent": request.intent.value,
        "selector": {
            "name": request.selector.name,
            "scope_ref": request.selector.scope_ref,
            "resource_type": request.selector.resource_type,
            "resource_group": request.selector.resource_group,
        },
        "lookback_seconds": request.lookback_seconds,
        "requested_evidence": [item.value for item in request.requested_evidence],
        "budget": {
            "max_wall_seconds": request.budget.max_wall_seconds,
            "max_cost_microusd": request.budget.max_cost_microusd,
            "max_tool_calls": request.budget.max_tool_calls,
            "max_results": request.budget.max_results,
            "max_output_bytes": request.budget.max_output_bytes,
        },
        "idempotency_key": request.idempotency_key,
        "created_at": request.created_at.isoformat(),
        "explicit_deep": request.explicit_deep,
    }


def usage_to_dict(usage: ReadInvestigationRunUsage) -> dict[str, int | None]:
    return {
        "tool_calls": usage.tool_calls,
        "execution_duration_ms": usage.execution_duration_ms,
        "reserved_cost_microusd": usage.reserved_cost_microusd,
        "measured_cost_microusd": usage.measured_cost_microusd,
    }


def result_to_dict(result: ReadInvestigationResult) -> dict[str, object]:
    return {
        "outcome": result.outcome.value,
        "resolution": _resolution_to_dict(result.resolution),
        "evidence": [_evidence_to_dict(item) for item in result.evidence],
        "receipts": [_receipt_to_dict(item) for item in result.receipts],
        "progress_kinds": list(result.progress_kinds),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }


def qualified_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in COLUMNS.split(","))


def _request(raw: dict[str, Any]) -> ReadInvestigationRequest:
    selector = _mapping(raw["selector"])
    budget = _mapping(raw["budget"])
    return ReadInvestigationRequest(
        requester_ref=str(raw["requester_ref"]),
        conversation_ref=str(raw["conversation_ref"]),
        correlation_ref=str(raw["correlation_ref"]),
        intent=ReadInvestigationIntent(str(raw["intent"])),
        selector=ResourceSelector(
            name=str(selector["name"]),
            scope_ref=str(selector["scope_ref"]),
            resource_type=(
                str(selector["resource_type"])
                if selector.get("resource_type") is not None
                else None
            ),
            resource_group=(
                str(selector["resource_group"])
                if selector.get("resource_group") is not None
                else None
            ),
        ),
        lookback_seconds=int(raw["lookback_seconds"]),
        requested_evidence=tuple(
            ReadToolId(str(tool_id)) for tool_id in raw.get("requested_evidence", [])
        ),
        budget=ReadInvestigationBudget(
            max_wall_seconds=int(budget["max_wall_seconds"]),
            max_cost_microusd=int(budget["max_cost_microusd"]),
            max_tool_calls=int(budget["max_tool_calls"]),
            max_results=int(budget["max_results"]),
            max_output_bytes=int(budget["max_output_bytes"]),
        ),
        idempotency_key=str(raw["idempotency_key"]),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        explicit_deep=bool(raw.get("explicit_deep", False)),
    )


def _usage(raw: dict[str, Any]) -> ReadInvestigationRunUsage:
    return ReadInvestigationRunUsage(
        tool_calls=int(raw["tool_calls"]),
        execution_duration_ms=int(raw["execution_duration_ms"]),
        reserved_cost_microusd=int(raw.get("reserved_cost_microusd", 0)),
        measured_cost_microusd=(
            int(raw["measured_cost_microusd"])
            if raw.get("measured_cost_microusd") is not None
            else None
        ),
    )


def _result(raw: dict[str, Any], *, request: ReadInvestigationRequest) -> ReadInvestigationResult:
    return ReadInvestigationResult(
        request=request,
        outcome=ReadInvestigationOutcome(str(raw["outcome"])),
        resolution=_resolution(_mapping(raw["resolution"])),
        evidence=tuple(_evidence(_mapping(item)) for item in raw.get("evidence", [])),
        receipts=tuple(_receipt(_mapping(item)) for item in raw.get("receipts", [])),
        progress_kinds=tuple(str(item) for item in raw["progress_kinds"]),
        started_at=datetime.fromisoformat(str(raw["started_at"])),
        finished_at=datetime.fromisoformat(str(raw["finished_at"])),
    )


def _resolution_to_dict(resolution: ResourceResolution) -> dict[str, object]:
    return {
        "status": resolution.status.value,
        "resource": (
            {
                "resource_ref": resolution.resource.resource_ref,
                "scope_ref": resolution.resource.scope_ref,
                "name": resolution.resource.name,
                "resource_type": resolution.resource.resource_type,
                "resource_group": resolution.resource.resource_group,
            }
            if resolution.resource is not None
            else None
        ),
        "candidates": [
            {
                "resource_ref": item.resource_ref,
                "name": item.name,
                "resource_type": item.resource_type,
                "resource_group": item.resource_group,
            }
            for item in resolution.candidates
        ],
        "detail": resolution.detail,
    }


def _resolution(raw: dict[str, Any]) -> ResourceResolution:
    resource_raw = raw.get("resource")
    return ResourceResolution(
        status=ResourceResolutionStatus(str(raw["status"])),
        resource=(
            ResolvedResource(
                resource_ref=str(_mapping(resource_raw)["resource_ref"]),
                scope_ref=str(_mapping(resource_raw)["scope_ref"]),
                name=str(_mapping(resource_raw)["name"]),
                resource_type=str(_mapping(resource_raw)["resource_type"]),
                resource_group=(
                    str(_mapping(resource_raw)["resource_group"])
                    if _mapping(resource_raw).get("resource_group") is not None
                    else None
                ),
            )
            if resource_raw is not None
            else None
        ),
        candidates=tuple(
            ResourceCandidate(
                resource_ref=str(_mapping(item)["resource_ref"]),
                name=str(_mapping(item)["name"]),
                resource_type=str(_mapping(item)["resource_type"]),
                resource_group=(
                    str(_mapping(item)["resource_group"])
                    if _mapping(item).get("resource_group") is not None
                    else None
                ),
            )
            for item in raw.get("candidates", [])
        ),
        detail=str(raw["detail"]) if raw.get("detail") is not None else None,
    )


def _evidence_to_dict(envelope: ReadEvidenceEnvelope) -> dict[str, object]:
    return {
        "status": envelope.status.value,
        "authority": envelope.authority,
        "resource_ref": envelope.resource_ref,
        "observed_at": envelope.observed_at.isoformat(),
        "freshness": envelope.freshness.value,
        "truncated": envelope.truncated,
        "records": [_record_to_dict(item) for item in envelope.records],
        "evidence_refs": list(envelope.evidence_refs),
        "limitations": [item.value for item in envelope.limitations],
        "truncation_reason": (
            envelope.truncation_reason.value if envelope.truncation_reason is not None else None
        ),
    }


def _evidence(raw: dict[str, Any]) -> ReadEvidenceEnvelope:
    truncated = bool(raw["truncated"])
    raw_reason = raw.get("truncation_reason")
    truncation_reason = (
        EvidenceLimitationKind(str(raw_reason))
        if raw_reason is not None
        else EvidenceLimitationKind.UNSPECIFIED
        if truncated
        else None
    )
    limitations = tuple(EvidenceLimitationKind(str(item)) for item in raw.get("limitations", []))
    if truncation_reason is not None and truncation_reason not in limitations:
        limitations = (*limitations, truncation_reason)
    return ReadEvidenceEnvelope(
        status=EvidenceStatus(str(raw["status"])),
        authority=str(raw["authority"]),
        resource_ref=str(raw["resource_ref"]),
        observed_at=datetime.fromisoformat(str(raw["observed_at"])),
        freshness=EvidenceFreshness(str(raw["freshness"])),
        truncated=truncated,
        records=tuple(_record(_mapping(item)) for item in raw.get("records", [])),
        evidence_refs=tuple(str(item) for item in raw.get("evidence_refs", [])),
        limitations=limitations,
        truncation_reason=truncation_reason,
    )


def _record_to_dict(record: ReadEvidenceRecord) -> dict[str, object]:
    return {
        "occurred_at": record.occurred_at.isoformat(),
        "status": record.status,
        "operation_kind": record.operation_kind,
        "actor_ref": record.actor_ref,
        "actor_kind": record.actor_kind.value if record.actor_kind is not None else None,
        "correlation_ref": record.correlation_ref,
        "state": record.state,
        "health_kind": record.health_kind,
    }


def _record(raw: dict[str, Any]) -> ReadEvidenceRecord:
    actor_kind = raw.get("actor_kind")
    return ReadEvidenceRecord(
        occurred_at=datetime.fromisoformat(str(raw["occurred_at"])),
        status=str(raw["status"]),
        operation_kind=(
            str(raw["operation_kind"]) if raw.get("operation_kind") is not None else None
        ),
        actor_ref=str(raw["actor_ref"]) if raw.get("actor_ref") is not None else None,
        actor_kind=ActorKind(str(actor_kind)) if actor_kind is not None else None,
        correlation_ref=(
            str(raw["correlation_ref"]) if raw.get("correlation_ref") is not None else None
        ),
        state=str(raw["state"]) if raw.get("state") is not None else None,
        health_kind=str(raw["health_kind"]) if raw.get("health_kind") is not None else None,
    )


def _receipt_to_dict(receipt: ToolCallReceipt) -> dict[str, object]:
    return {
        "outcome": receipt.outcome.value,
        "receipt_ref": receipt.receipt_ref,
        "already_existed": receipt.already_existed,
        "rollback_succeeded": receipt.rollback_succeeded,
        "detail": receipt.detail,
        "tool_id": receipt.tool_id,
        "transport": receipt.transport,
        "operation_class": receipt.operation_class,
        "queue_duration_ms": receipt.queue_duration_ms,
        "execution_duration_ms": receipt.execution_duration_ms,
        "cost_microusd": receipt.cost_microusd,
        "result_count": receipt.result_count,
        "truncated": receipt.truncated,
        "cache_status": receipt.cache_status,
        "recorded_at": receipt.recorded_at.isoformat() if receipt.recorded_at is not None else None,
        "trace_ref": receipt.trace_ref,
    }


def _receipt(raw: dict[str, Any]) -> ToolCallReceipt:
    recorded_at = raw.get("recorded_at")
    return ToolCallReceipt(
        outcome=ToolCallOutcome(str(raw["outcome"])),
        receipt_ref=str(raw["receipt_ref"]),
        already_existed=bool(raw.get("already_existed", False)),
        rollback_succeeded=(
            bool(raw["rollback_succeeded"]) if raw.get("rollback_succeeded") is not None else None
        ),
        detail=str(raw["detail"]) if raw.get("detail") is not None else None,
        tool_id=str(raw["tool_id"]) if raw.get("tool_id") is not None else None,
        transport=str(raw["transport"]) if raw.get("transport") is not None else None,
        operation_class=(
            str(raw["operation_class"]) if raw.get("operation_class") is not None else None
        ),
        queue_duration_ms=int(raw.get("queue_duration_ms", 0)),
        execution_duration_ms=int(raw.get("execution_duration_ms", 0)),
        cost_microusd=(int(raw["cost_microusd"]) if raw.get("cost_microusd") is not None else None),
        result_count=int(raw.get("result_count", 0)),
        truncated=bool(raw.get("truncated", False)),
        cache_status=str(raw["cache_status"]) if raw.get("cache_status") is not None else None,
        recorded_at=(datetime.fromisoformat(str(recorded_at)) if recorded_at is not None else None),
        trace_ref=str(raw["trace_ref"]) if raw.get("trace_ref") is not None else None,
    )


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    raise RuntimeError("read investigation JSON column is not an object")
