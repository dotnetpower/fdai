"""Project durable source rows into validated operational activity records."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from fdai_service_contracts import (
    AgentOperationalActivity,
    ObservationDomain,
    OperationalActivityKind,
    OperationalActivityResultState,
    OperationalActivityResultUnit,
    OperationalActivityScopeClass,
    OperationalActivityStatus,
    OperationalActivitySummaryKey,
    OperationalFreshness,
)

MAX_ACTIVITY_DURATION_MS = 86_400_000
ObservationOwner = Literal["Huginn", "Heimdall", "Njord", "Freyr", "Vidar"]


def durable_activity_projection(
    *,
    inventory_rows: Sequence[Mapping[str, Any]],
    ontology_rows: Sequence[Mapping[str, Any]],
    read_rows: Sequence[Mapping[str, Any]],
    observation_rows: Sequence[Mapping[str, Any]] = (),
    limit: int,
) -> dict[str, object]:
    """Validate and merge bounded durable activities newest first."""
    activities = [
        *(_inventory_activity(row) for row in inventory_rows),
        *(_ontology_activity(row) for row in ontology_rows),
        *(_read_activity(row) for row in read_rows),
        *(_observation_activity(row) for row in observation_rows),
    ]
    by_id: dict[str, AgentOperationalActivity] = {}
    for activity in activities:
        existing = by_id.get(activity.activity_id)
        if existing is None or activity.observed_at > existing.observed_at:
            by_id[activity.activity_id] = activity
    activities = list(by_id.values())
    activities.sort(key=lambda activity: activity.observed_at, reverse=True)
    return {
        "items": [activity.model_dump(mode="json") for activity in activities[:limit]],
        "snapshot_at": datetime.now(tz=UTC).isoformat(),
        "source": "durable-operational-projection",
    }


def _inventory_activity(row: Mapping[str, Any]) -> AgentOperationalActivity:
    attempt_id = _text(row.get("id"), "inventory attempt id", maximum=512)
    source = _text(row.get("source"), "inventory source", maximum=128)
    status_value = _text(row.get("status"), "inventory status", maximum=32)
    statuses = {
        "collecting": OperationalActivityStatus.STARTED,
        "active": OperationalActivityStatus.COMPLETED,
        "superseded": OperationalActivityStatus.SUPERSEDED,
        "failed": OperationalActivityStatus.FAILED,
    }
    try:
        status = statuses[status_value]
    except KeyError as exc:
        raise ValueError("inventory status is unsupported") from exc
    started_at = _timestamp(row.get("started_at"), "inventory started_at")
    completed_at = (
        _timestamp(row.get("completed_at"), "inventory completed_at")
        if row.get("completed_at") is not None
        else None
    )
    observed_at = completed_at or started_at
    measured_duration_ms = (
        round((completed_at - started_at).total_seconds() * 1000)
        if completed_at is not None
        else None
    )
    duration_ms = (
        measured_duration_ms
        if measured_duration_ms is not None
        and 0 <= measured_duration_ms <= MAX_ACTIVITY_DURATION_MS
        else None
    )
    duration_reasons = (
        ("duration_out_of_range",)
        if measured_duration_ms is not None and duration_ms is None
        else ()
    )
    failure_code = row.get("failure_code")
    reason_codes = (
        (_text(failure_code, "inventory failure code", maximum=128),)
        if status is OperationalActivityStatus.FAILED
        else ()
    ) + duration_reasons
    evidence_count = _count(row, "resource_count") + _count(row, "link_count")
    if status is OperationalActivityStatus.STARTED:
        result_state = OperationalActivityResultState.NOT_RECORDED
    elif status is OperationalActivityStatus.FAILED:
        result_state = OperationalActivityResultState.UNAVAILABLE
    else:
        result_state = OperationalActivityResultState.MEASURED
    return AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id=f"inventory.scan:{attempt_id}:{status.value}",
        activity_instance_id=f"inventory.scan:{attempt_id}",
        idempotency_key=f"inventory.scan:{attempt_id}:{status.value}",
        kind=OperationalActivityKind.INVENTORY_SCAN,
        status=status,
        owner_agent="Huginn",
        producer="inventory-sync-job",
        observed_at=observed_at,
        source=source,
        freshness=(
            OperationalFreshness.UNAVAILABLE
            if status is OperationalActivityStatus.FAILED
            else OperationalFreshness.UNKNOWN
        ),
        evidence_count=evidence_count,
        duration_ms=duration_ms,
        correlation_id=attempt_id,
        reason_codes=reason_codes,
        summary_key=OperationalActivitySummaryKey.INVENTORY_COLLECTION,
        scope_class=OperationalActivityScopeClass.CONFIGURED_ESTATE,
        result_state=result_state,
        result_count=(
            evidence_count if result_state is OperationalActivityResultState.MEASURED else None
        ),
        result_unit=(
            OperationalActivityResultUnit.EVIDENCE_ITEMS
            if result_state is OperationalActivityResultState.MEASURED
            else None
        ),
        source_cutoff=completed_at,
        started_at=started_at,
        completed_at=completed_at,
    )


def _ontology_activity(row: Mapping[str, Any]) -> AgentOperationalActivity:
    value = _mapping(row.get("value"), "ontology activity value")
    generation = _text(value.get("generation"), "ontology generation", maximum=512)
    source_status = _text(value.get("status"), "ontology status", maximum=32)
    available = source_status == "available"
    if not available and source_status != "unavailable":
        raise ValueError("ontology status is unsupported")
    reasons = _string_tuple(value.get("dropped_reasons"), "ontology dropped reasons")
    if not available and not reasons:
        reasons = ("projection_unavailable",)
    status = (
        OperationalActivityStatus.COMPLETED if available else OperationalActivityStatus.DEGRADED
    )
    observed_at = _timestamp(row.get("updated_at"), "ontology updated_at")
    return AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id=f"inventory.ontology-projection:{generation}:{status.value}",
        activity_instance_id=f"inventory.ontology-projection:{generation}",
        idempotency_key=f"inventory.ontology-projection:{generation}:{status.value}",
        kind=OperationalActivityKind.INVENTORY_ONTOLOGY_PROJECTION,
        status=status,
        owner_agent="Heimdall",
        producer="inventory-sync-job",
        observed_at=observed_at,
        source="inventory-ontology",
        freshness=(OperationalFreshness.FRESH if available else OperationalFreshness.UNAVAILABLE),
        reason_codes=reasons,
        correlation_id=generation,
        summary_key=OperationalActivitySummaryKey.ONTOLOGY_PROJECTION,
        scope_class=OperationalActivityScopeClass.CONFIGURED_ESTATE,
        result_state=(
            OperationalActivityResultState.NOT_RECORDED
            if available
            else OperationalActivityResultState.UNAVAILABLE
        ),
        source_cutoff=observed_at,
        completed_at=observed_at,
    )


def _read_activity(row: Mapping[str, Any]) -> AgentOperationalActivity:
    sample = _mapping(row.get("sample"), "read activity sample")
    succeeded = sample.get("succeeded")
    if not isinstance(succeeded, bool):
        raise ValueError("read activity succeeded MUST be boolean")
    recorded_at = _timestamp(sample.get("recorded_at"), "read activity recorded_at")
    correlation_ref = _text(
        sample.get("correlation_ref"),
        "read activity correlation_ref",
        maximum=256,
    )
    status = (
        OperationalActivityStatus.COMPLETED if succeeded else OperationalActivityStatus.DEGRADED
    )
    tool_id = _text(row.get("tool_id"), "read activity tool_id", maximum=96)
    evidence_count = 1 if succeeded else 0
    return AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id=f"current-state.read:{correlation_ref}:{status.value}",
        activity_instance_id=f"current-state.read:{correlation_ref}",
        idempotency_key=f"current-state.read:{correlation_ref}:{status.value}",
        kind=OperationalActivityKind.CURRENT_STATE_READ,
        status=status,
        owner_agent="Heimdall",
        producer="core-control-plane",
        observed_at=recorded_at,
        source=f"read-investigation:{tool_id}",
        freshness=(OperationalFreshness.FRESH if succeeded else OperationalFreshness.UNAVAILABLE),
        evidence_count=evidence_count,
        duration_ms=_count(sample, "queue_duration_ms") + _count(sample, "execution_duration_ms"),
        correlation_id=correlation_ref,
        reason_codes=() if succeeded else ("read_failed",),
        summary_key=OperationalActivitySummaryKey.CURRENT_STATE_OBSERVATION,
        scope_class=OperationalActivityScopeClass.INVESTIGATION,
        result_state=(
            OperationalActivityResultState.MEASURED
            if succeeded
            else OperationalActivityResultState.UNAVAILABLE
        ),
        result_count=evidence_count if succeeded else None,
        result_unit=(OperationalActivityResultUnit.EVIDENCE_ITEMS if succeeded else None),
        source_cutoff=recorded_at,
        completed_at=recorded_at,
    )


def _observation_activity(row: Mapping[str, Any]) -> AgentOperationalActivity:
    value = _mapping(row.get("value"), "observation activity value")
    source_id = _text(value.get("source_id"), "observation source id", maximum=96)
    campaign_id = _text(value.get("campaign_id"), "observation campaign id", maximum=96)
    try:
        domain = ObservationDomain(_text(value.get("domain"), "observation domain", maximum=64))
    except ValueError as exc:
        raise ValueError("observation domain is unsupported") from exc
    owners: Mapping[ObservationDomain, ObservationOwner] = {
        ObservationDomain.INVENTORY: "Huginn",
        ObservationDomain.ACTIVITY_LOG: "Huginn",
        ObservationDomain.RESOURCE_HEALTH: "Heimdall",
        ObservationDomain.SERVICE_HEALTH: "Heimdall",
        ObservationDomain.METRICS: "Heimdall",
        ObservationDomain.LOGS: "Heimdall",
        ObservationDomain.GUEST_LOGS: "Heimdall",
        ObservationDomain.NETWORK_CONFIG: "Heimdall",
        ObservationDomain.COST: "Njord",
        ObservationDomain.RECOVERY: "Vidar",
    }
    status_value = _text(value.get("status"), "observation status", maximum=32)
    statuses = {
        "started": OperationalActivityStatus.STARTED,
        "completed": OperationalActivityStatus.COMPLETED,
        "degraded": OperationalActivityStatus.DEGRADED,
        "failed": OperationalActivityStatus.FAILED,
        "superseded": OperationalActivityStatus.SUPERSEDED,
    }
    try:
        status = statuses[status_value]
    except KeyError as exc:
        raise ValueError("observation status is not terminal") from exc
    if status is OperationalActivityStatus.STARTED:
        freshness = OperationalFreshness.UNKNOWN
    else:
        try:
            freshness = OperationalFreshness(
                _text(value.get("freshness"), "observation freshness", maximum=32)
            )
        except ValueError as exc:
            raise ValueError("observation freshness is unsupported") from exc
    reasons = _string_tuple(value.get("reason_codes"), "observation reason codes")
    evidence_count = _count(value, "evidence_count")
    started_at = (
        _timestamp(value.get("started_at"), "observation started_at")
        if value.get("started_at") is not None
        else None
    )
    completed_at = (
        _timestamp(value.get("completed_at"), "observation completed_at")
        if status is not OperationalActivityStatus.STARTED
        else None
    )
    observed_at = started_at if status is OperationalActivityStatus.STARTED else completed_at
    if observed_at is None:
        raise ValueError("observation activity timestamp MUST be present")
    if status in {
        OperationalActivityStatus.STARTED,
        OperationalActivityStatus.SUPERSEDED,
    }:
        result_state = OperationalActivityResultState.NOT_RECORDED
    elif (
        status is OperationalActivityStatus.FAILED
        or evidence_count == 0
        and freshness is OperationalFreshness.UNAVAILABLE
    ):
        result_state = OperationalActivityResultState.UNAVAILABLE
    else:
        result_state = OperationalActivityResultState.MEASURED
    return AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id=f"observation:{source_id}:{campaign_id}:{status.value}",
        activity_instance_id=f"observation:{source_id}:{campaign_id}",
        idempotency_key=f"observation:{source_id}:{campaign_id}:{status.value}",
        kind=OperationalActivityKind.OBSERVATION,
        status=status,
        owner_agent=owners[domain],
        producer="observation-campaign-job",
        observation_domain=domain,
        observed_at=observed_at,
        source=source_id,
        freshness=freshness,
        evidence_count=evidence_count,
        duration_ms=_optional_count(value, "duration_ms"),
        correlation_id=campaign_id,
        reason_codes=reasons,
        summary_key=OperationalActivitySummaryKey.SOURCE_OBSERVATION,
        scope_class=OperationalActivityScopeClass.SOURCE_DOMAIN,
        result_state=result_state,
        result_count=(
            evidence_count if result_state is OperationalActivityResultState.MEASURED else None
        ),
        result_unit=(
            OperationalActivityResultUnit.RECORDS
            if result_state is OperationalActivityResultState.MEASURED
            else None
        ),
        source_cutoff=completed_at,
        started_at=started_at,
        completed_at=completed_at,
    )


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} MUST be an object") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} MUST be an object")
    return value


def _text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} MUST be bounded text")
    return value.strip()


def _timestamp(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} MUST be RFC 3339") from exc
    else:
        raise ValueError(f"{field} MUST be RFC 3339")
    if parsed.tzinfo is None:
        raise ValueError(f"{field} MUST include a timezone")
    return parsed.astimezone(UTC)


def _count(value: Mapping[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 1_000_000:
        raise ValueError(f"{field} MUST be a bounded count")
    return item


def _optional_count(value: Mapping[str, Any], field: str) -> int | None:
    item = value.get(field)
    if item is None:
        return None
    if not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 86_400_000:
        raise ValueError(f"{field} MUST be a bounded count")
    return item


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError(f"{field} MUST be a bounded array")
    items = tuple(_text(item, field, maximum=128) for item in value)
    if len(set(items)) != len(items):
        raise ValueError(f"{field} MUST contain unique values")
    return items


__all__ = ["durable_activity_projection"]
