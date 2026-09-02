"""Read-only FunctionType for active subscription Service Health evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

SERVICE_HEALTH_FUNCTION_NAME = "query.subscription_service_health"
SERVICE_HEALTH_MEASURE_CONCEPTS = ("service_health.active_event",)
SERVICE_HEALTH_EVENT_TYPES = frozenset({"service_issue", "planned_maintenance", "health_advisory"})
SERVICE_HEALTH_EVENT_TYPE_MEASURES = {
    event_type: f"service_health.{event_type}" for event_type in sorted(SERVICE_HEALTH_EVENT_TYPES)
}
SERVICE_HEALTH_ALL_MEASURE_CONCEPTS = (
    *SERVICE_HEALTH_MEASURE_CONCEPTS,
    *SERVICE_HEALTH_EVENT_TYPE_MEASURES.values(),
)
_MAX_ROWS = 256
SERVICE_HEALTH_MAX_OBSERVATIONS = _MAX_ROWS - 1


@dataclass(frozen=True, slots=True)
class ServiceHealthObservation:
    """One active event projected with at most one impacted-resource record."""

    event_id: str
    event_type: str
    title: str
    level: str | None
    status: str
    impact_start_at: datetime
    observed_at: datetime
    impacted_resource_count: int | None
    impacted_resource_ref: str | None
    resource_name: str | None
    resource_type: str | None
    resource_group: str | None
    region: str | None
    impact_status: str | None
    event_evidence_ref: str
    impact_evidence_ref: str | None

    def __post_init__(self) -> None:
        if self.event_type not in SERVICE_HEALTH_EVENT_TYPES:
            raise ValueError("Service Health event_type is not reviewed")
        for name, value, maximum in (
            ("event_id", self.event_id, 256),
            ("title", self.title, 512),
            ("status", self.status, 64),
            ("event_evidence_ref", self.event_evidence_ref, 256),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"Service Health {name} MUST be bounded and non-empty")
        for name, optional_value, maximum in (
            ("resource_name", self.resource_name, 256),
            ("impacted_resource_ref", self.impacted_resource_ref, 256),
            ("resource_type", self.resource_type, 256),
            ("resource_group", self.resource_group, 256),
            ("region", self.region, 128),
            ("level", self.level, 64),
            ("impact_status", self.impact_status, 64),
            ("impact_evidence_ref", self.impact_evidence_ref, 256),
        ):
            if optional_value is not None and (
                not optional_value.strip() or len(optional_value) > maximum
            ):
                raise ValueError(f"Service Health {name} MUST be bounded when present")
        if self.impact_start_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("Service Health timestamps MUST be timezone-aware")
        if self.impact_start_at > self.observed_at:
            raise ValueError("Service Health impact start cannot follow observation time")
        if self.impacted_resource_count is not None and not (
            0 <= self.impacted_resource_count <= _MAX_ROWS
        ):
            raise ValueError("Service Health impacted_resource_count is out of bounds")
        has_impact = self.impact_evidence_ref is not None
        if has_impact != any(
            value is not None
            for value in (
                self.resource_name,
                self.impacted_resource_ref,
                self.resource_type,
                self.resource_group,
                self.region,
                self.impact_status,
            )
        ):
            raise ValueError("Service Health impact projection is inconsistent")
        if has_impact and (
            self.impacted_resource_count is None or self.impacted_resource_count < 1
        ):
            raise ValueError("Service Health impact row requires a positive observed count")
        if not has_impact and self.impacted_resource_count not in {0, None}:
            raise ValueError("Service Health event-only row has an invalid impact count")


@dataclass(frozen=True, slots=True)
class ServiceHealthCollection:
    """Bounded active Service Health evidence from one server-owned subscription."""

    observations: tuple[ServiceHealthObservation, ...]
    observed_at: datetime
    complete: bool
    limitation: str | None
    attempt_ref: str

    def __post_init__(self) -> None:
        if len(self.observations) > SERVICE_HEALTH_MAX_OBSERVATIONS:
            raise ValueError("Service Health collection exceeds its row bound")
        ordering = tuple(
            (
                item.impact_start_at,
                item.event_id,
                item.resource_name or "",
                item.event_evidence_ref,
                item.impact_evidence_ref or "",
            )
            for item in self.observations
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError("Service Health observations MUST be deterministically ordered")
        if self.observed_at.tzinfo is None:
            raise ValueError("Service Health collection time MUST be timezone-aware")
        if any(item.observed_at != self.observed_at for item in self.observations):
            raise ValueError("Service Health rows MUST share the collection observation time")
        if self.complete == (self.limitation is not None):
            raise ValueError("Service Health completeness and limitation are inconsistent")
        if not self.attempt_ref.strip() or len(self.attempt_ref) > 256:
            raise ValueError("Service Health attempt_ref MUST be bounded and non-empty")


class ServiceHealthReader(Protocol):
    """Read active Service Health events from composition-owned provider scope."""

    async def read_active(self) -> ServiceHealthCollection: ...


def service_health_function_type() -> OntologyFunctionType:
    """Declare the server-scoped active Service Health read contract."""

    return OntologyFunctionType(
        name=SERVICE_HEALTH_FUNCTION_NAME,
        version="1.1.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "event_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(SERVICE_HEALTH_EVENT_TYPES)},
                    "minItems": 1,
                    "maxItems": len(SERVICE_HEALTH_EVENT_TYPES),
                    "uniqueItems": True,
                }
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "x-fdai-measure-concepts": list(SERVICE_HEALTH_ALL_MEASURE_CONCEPTS),
            "properties": {
                "rows": {"type": "array", "maxItems": _MAX_ROWS},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=15,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def service_health_function(
    ontology_release: OntologyRelease,
    *,
    reader: ServiceHealthReader,
) -> ContextualOntologyFunction:
    """Project active events while preserving verified zero and unavailable evidence."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        SERVICE_HEALTH_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("Service Health purpose does not match invocation context")
        if set(arguments) - {"event_types"}:
            raise ValueError("Service Health accepts only reviewed event type filters")
        raw_event_types = arguments.get("event_types")
        if raw_event_types is None:
            event_types = SERVICE_HEALTH_EVENT_TYPES
        elif (
            not isinstance(raw_event_types, list)
            or not raw_event_types
            or any(not isinstance(item, str) for item in raw_event_types)
            or len(raw_event_types) != len(set(raw_event_types))
            or not set(raw_event_types) <= SERVICE_HEALTH_EVENT_TYPES
        ):
            raise ValueError("Service Health event_types are invalid")
        else:
            event_types = frozenset(raw_event_types)
        collection = await reader.read_active()
        observations = tuple(
            item for item in collection.observations if item.event_type in event_types
        )
        unique_events = {item.event_id for item in observations}
        impacted_resources = {
            item.impacted_resource_ref
            for item in observations
            if item.impacted_resource_ref is not None
        }
        active_event_count = len(unique_events) if collection.complete or unique_events else None
        impacted_resource_count = (
            len(impacted_resources) if collection.complete or impacted_resources else None
        )
        count_posture = (
            "exact" if collection.complete else "minimum" if unique_events else "unknown"
        )
        summary = QueryRow.from_values(
            "service-health-summary",
            {
                "record_kind": "summary",
                "scope_kind": "subscription",
                "active_event_count": active_event_count,
                "impacted_resource_count": impacted_resource_count,
                "count_posture": count_posture,
                "observed_at": collection.observed_at.isoformat(),
                "attempt_ref": collection.attempt_ref,
                "execution_authority": False,
            },
        )
        event_rows = tuple(
            QueryRow.from_values(
                f"service-health-event-{index:04d}",
                {
                    "record_kind": "event",
                    "scope_kind": "subscription",
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "title": item.title,
                    "level": item.level,
                    "status": item.status,
                    "impact_start_at": item.impact_start_at.isoformat(),
                    "observed_at": item.observed_at.isoformat(),
                    "impacted_resource_count": item.impacted_resource_count,
                    "impacted_resource_ref": item.impacted_resource_ref,
                    "resource_name": item.resource_name,
                    "resource_type": item.resource_type,
                    "resource_group": item.resource_group,
                    "region": item.region,
                    "impact_status": item.impact_status,
                    "event_evidence_ref": item.event_evidence_ref,
                    "impact_evidence_ref": item.impact_evidence_ref,
                    "execution_authority": False,
                },
            )
            for index, item in enumerate(observations, start=1)
        )
        table = QueryTable(
            rows=(summary, *event_rows),
            complete=collection.complete,
            truncation_reason=collection.limitation,
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


__all__ = [
    "SERVICE_HEALTH_EVENT_TYPES",
    "SERVICE_HEALTH_EVENT_TYPE_MEASURES",
    "SERVICE_HEALTH_FUNCTION_NAME",
    "SERVICE_HEALTH_ALL_MEASURE_CONCEPTS",
    "SERVICE_HEALTH_MEASURE_CONCEPTS",
    "SERVICE_HEALTH_MAX_OBSERVATIONS",
    "ServiceHealthCollection",
    "ServiceHealthObservation",
    "ServiceHealthReader",
    "service_health_function",
    "service_health_function_type",
]
