"""Read-only FunctionType for bounded Resource event history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

RESOURCE_EVENT_FUNCTION_NAME = "query.resource_event_history"
RESOURCE_HEALTH_EVENT_FAMILY = "resource_event.resource_health"
KUBERNETES_EVENT_FAMILY = "resource_event.kubernetes"
RESOURCE_EVENT_MEASURE_CONCEPTS = (
    RESOURCE_HEALTH_EVENT_FAMILY,
    KUBERNETES_EVENT_FAMILY,
)
_MAX_RESOURCES = 1000
_MAX_EVENTS = 256


@dataclass(frozen=True, slots=True)
class ResourceEventObservation:
    """One normalized historical event bound to a requested logical resource."""

    resource_id: str
    event_family: str
    event_kind: str
    status: str
    classification: str
    occurred_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("resource_id", self.resource_id, 1024),
            ("event_family", self.event_family, 128),
            ("event_kind", self.event_kind, 128),
            ("status", self.status, 128),
            ("classification", self.classification, 64),
            ("evidence_ref", self.evidence_ref, 256),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"Resource event {name} MUST be bounded and non-empty")
        if self.event_family not in RESOURCE_EVENT_MEASURE_CONCEPTS:
            raise ValueError("Resource event family is not reviewed")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Resource event occurred_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ResourceEventCollection:
    """Bounded provider history that repeats the exact requested resource scope."""

    resource_ids: tuple[str, ...]
    events: tuple[ResourceEventObservation, ...]
    observed_at: datetime
    complete: bool
    limitation: str | None
    attempt_ref: str

    def __post_init__(self) -> None:
        if not self.resource_ids or len(self.resource_ids) > _MAX_RESOURCES:
            raise ValueError("Resource event scope MUST contain between 1 and 1000 resources")
        if self.resource_ids != tuple(sorted(set(self.resource_ids))):
            raise ValueError("Resource event scope MUST be unique and ordered")
        if len(self.events) > _MAX_EVENTS:
            raise ValueError("Resource event collection exceeds its event bound")
        if any(item.resource_id not in self.resource_ids for item in self.events):
            raise ValueError("Resource event collection widened the requested scope")
        ordering = tuple((item.occurred_at, item.evidence_ref) for item in self.events)
        if ordering != tuple(sorted(ordering)):
            raise ValueError("Resource events MUST be deterministically ordered")
        if self.observed_at.tzinfo is None:
            raise ValueError("Resource event collection time MUST be timezone-aware")
        if self.complete == (self.limitation is not None):
            raise ValueError("Resource event completeness and limitation are inconsistent")
        if not self.attempt_ref.strip() or len(self.attempt_ref) > 256:
            raise ValueError("Resource event attempt_ref MUST be bounded and non-empty")


class ResourceEventCollectionReader(Protocol):
    """Read one reviewed history family for an exact server-selected resource set."""

    async def read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection: ...


class ResourceEventIdentityReader(Protocol):
    """Narrow a history read with receipt-bound immutable identity hints."""

    async def read_history_with_identity(
        self,
        *,
        resource_ids: tuple[str, ...],
        resource_identity: Mapping[str, Mapping[str, str]],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection: ...


def resource_event_function_type() -> OntologyFunctionType:
    """Declare bounded Resource Health history over a secured collection."""

    return OntologyFunctionType(
        name=RESOURCE_EVENT_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "event_families", "lookback_seconds"],
            "properties": {
                "query_result": {"type": "object", "x-fdai-dependency-only": True},
                "event_families": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": len(RESOURCE_EVENT_MEASURE_CONCEPTS),
                    "uniqueItems": True,
                    "items": {"enum": list(RESOURCE_EVENT_MEASURE_CONCEPTS)},
                },
                "lookback_seconds": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 86400,
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "x-fdai-measure-concepts": list(RESOURCE_EVENT_MEASURE_CONCEPTS),
            "properties": {
                "rows": {"type": "array", "maxItems": _MAX_EVENTS},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
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


def resource_event_history_function(
    ontology_release: OntologyRelease,
    *,
    reader: ResourceEventCollectionReader,
) -> ContextualOntologyFunction:
    """Read exact history and preserve zero events separately from unavailable evidence."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_EVENT_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("resource event purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="resource_scope_incomplete")
        objects = tuple(sorted(secured.materialization.graph.objects, key=lambda item: item.id))
        if not objects:
            return _table((), complete=True, reason=None)
        if len(objects) > _MAX_RESOURCES:
            return _table((), complete=False, reason="resource_event_scope_limit")
        event_families = tuple(str(item) for item in arguments["event_families"])
        lookback_seconds = int(arguments["lookback_seconds"])
        resource_ids = tuple(item.id for item in objects)
        identity_read = getattr(reader, "read_history_with_identity", None)
        if callable(identity_read):
            collection = await identity_read(
                resource_ids=resource_ids,
                resource_identity=_resource_identity(objects),
                event_families=event_families,
                lookback_seconds=lookback_seconds,
            )
        else:
            collection = await reader.read_history(
                resource_ids=resource_ids,
                event_families=event_families,
                lookback_seconds=lookback_seconds,
            )
        if collection.resource_ids != resource_ids:
            raise ValueError("Resource event reader changed the secured resource scope")
        by_id = {item.id: item for item in objects}
        rows = tuple(
            QueryRow.from_values(
                f"resource-event-{index:04d}",
                {
                    "name": _text(by_id[event.resource_id].properties.get("name")),
                    "type": _text(by_id[event.resource_id].properties.get("type")),
                    "event_family": event.event_family,
                    "event_kind": event.event_kind,
                    "status": event.status,
                    "classification": event.classification,
                    "occurred_at": event.occurred_at.isoformat(),
                    "evidence_ref": event.evidence_ref,
                    "execution_authority": False,
                },
            )
            for index, event in enumerate(collection.events, start=1)
        )
        return _table(
            rows,
            complete=collection.complete,
            reason=collection.limitation,
        )

    return evaluate


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _resource_identity(
    objects: tuple[Any, ...],
) -> Mapping[str, Mapping[str, str]]:
    identity: dict[str, Mapping[str, str]] = {}
    for item in objects:
        provider_properties = item.properties.get("properties")
        if not isinstance(provider_properties, Mapping):
            continue
        fields = {
            name: value.strip()
            for name in ("cluster_ref", "uid")
            if isinstance((value := provider_properties.get(name)), str) and value.strip()
        }
        if fields:
            identity[item.id] = MappingProxyType(fields)
    return MappingProxyType(identity)


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = [
    "KUBERNETES_EVENT_FAMILY",
    "RESOURCE_EVENT_FUNCTION_NAME",
    "RESOURCE_HEALTH_EVENT_FAMILY",
    "RESOURCE_EVENT_MEASURE_CONCEPTS",
    "ResourceEventCollection",
    "ResourceEventCollectionReader",
    "ResourceEventIdentityReader",
    "ResourceEventObservation",
    "resource_event_function_type",
    "resource_event_history_function",
]
