"""Provider-neutral VM process CPU evidence for semantic investigations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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

_MAX_PROCESSES = 32
_MAX_SAMPLES = 10_000
VM_PROCESS_CPU_FUNCTION_NAME = "query.vm_process_cpu_evidence"


@dataclass(frozen=True, slots=True)
class VmProcessCpuObservation:
    """One bounded process CPU aggregate from an exact VM and time window."""

    resource_id: str
    process_name: str
    average_cpu_percent: float
    maximum_cpu_percent: float
    sample_count: int
    first_observed_at: datetime
    last_observed_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("resource_id", self.resource_id, 1024),
            ("process_name", self.process_name, 256),
            ("evidence_ref", self.evidence_ref, 256),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"VM process {name} MUST be bounded and non-empty")
        values = (self.average_cpu_percent, self.maximum_cpu_percent)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("VM process CPU values MUST be finite and non-negative")
        if self.maximum_cpu_percent < self.average_cpu_percent:
            raise ValueError("VM process maximum CPU MUST be at least the average")
        if not 1 <= self.sample_count <= _MAX_SAMPLES:
            raise ValueError("VM process sample_count MUST be in [1, 10000]")
        if self.first_observed_at.tzinfo is None or self.last_observed_at.tzinfo is None:
            raise ValueError("VM process observation times MUST be timezone-aware")
        if self.first_observed_at > self.last_observed_at:
            raise ValueError("VM process observation times MUST be ordered")


@dataclass(frozen=True, slots=True)
class VmProcessCpuCollection:
    """Bounded process aggregates that repeat one exact requested VM scope."""

    resource_id: str
    start: datetime
    end: datetime
    observed_at: datetime
    observations: tuple[VmProcessCpuObservation, ...]
    complete: bool
    truncated: bool
    limitation: str | None
    attempt_ref: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("resource_id", self.resource_id, 1024),
            ("attempt_ref", self.attempt_ref, 256),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"VM process collection {name} MUST be bounded and non-empty")
        if any(value.tzinfo is None for value in (self.start, self.end, self.observed_at)):
            raise ValueError("VM process collection times MUST be timezone-aware")
        if self.start >= self.end:
            raise ValueError("VM process collection window MUST be positive")
        if self.observed_at < self.end:
            raise ValueError("VM process collection observed_at MUST cover the requested window")
        if len(self.observations) > _MAX_PROCESSES:
            raise ValueError("VM process collection exceeds its process bound")
        if self.complete and not self.observations:
            raise ValueError("Complete VM process evidence requires at least one observation")
        if any(
            item.resource_id.casefold() != self.resource_id.casefold() for item in self.observations
        ):
            raise ValueError("VM process collection widened the requested scope")
        names = tuple(item.process_name.casefold() for item in self.observations)
        if len(set(names)) != len(names):
            raise ValueError("VM process collection identities MUST be unique")
        ordering = tuple(
            (-item.average_cpu_percent, -item.maximum_cpu_percent, item.process_name.casefold())
            for item in self.observations
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError("VM process observations MUST be deterministically ordered")
        if any(
            item.first_observed_at < self.start or item.last_observed_at > self.end
            for item in self.observations
        ):
            raise ValueError("VM process observations MUST stay inside the requested window")
        if self.complete != (self.limitation is None and not self.truncated):
            raise ValueError("VM process completeness, truncation, and limitation are inconsistent")
        if self.limitation is not None and (
            not self.limitation.strip() or len(self.limitation) > 128
        ):
            raise ValueError("VM process limitation MUST be bounded and non-empty")


class VmProcessCpuReader(Protocol):
    """Read bounded process CPU aggregates for one exact VM and time window."""

    async def read_process_cpu(
        self,
        *,
        resource_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> VmProcessCpuCollection: ...


def vm_process_cpu_function_type() -> OntologyFunctionType:
    """Declare bounded process CPU evidence over one secured VM Resource."""

    return OntologyFunctionType(
        name=VM_PROCESS_CPU_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "start", "end", "limit"],
            "properties": {
                "query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_PROCESSES},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": _MAX_PROCESSES},
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
        max_output_bytes=262_144,
        network_allowed=False,
        credentials_allowed=False,
    )


def vm_process_cpu_function(
    ontology_release: OntologyRelease,
    *,
    reader: VmProcessCpuReader,
) -> ContextualOntologyFunction:
    """Read process CPU only after one complete exact Resource receipt is supplied."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        VM_PROCESS_CPU_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("VM process evidence purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="resource_scope_incomplete")
        objects = secured.materialization.graph.objects
        if len(objects) != 1:
            return _table((), complete=False, reason="resource_scope_not_exact")
        resource = objects[0]
        if resource.object_type != "Resource":
            raise ValueError("VM process evidence requires one Resource target")
        start = datetime.fromisoformat(str(arguments["start"]))
        end = datetime.fromisoformat(str(arguments["end"]))
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("VM process function window MUST be aware and positive")
        if (end - start).total_seconds() > 3600:
            raise ValueError("VM process function window MUST NOT exceed one hour")
        if end > secured.receipt.observation_cutoff:
            raise ValueError("VM process function window exceeds the secured observation cutoff")
        limit = int(arguments["limit"])
        collection = await reader.read_process_cpu(
            resource_id=resource.id,
            start=start,
            end=end,
            limit=limit,
        )
        if collection.resource_id.casefold() != resource.id.casefold():
            raise ValueError("VM process reader changed the secured resource scope")
        if collection.start != start or collection.end != end:
            raise ValueError("VM process reader changed the requested time window")
        rows = tuple(
            QueryRow.from_values(
                f"vm-process-{index:04d}",
                {
                    "resource_id": resource.id,
                    "process_name": observation.process_name,
                    "average_cpu_percent": observation.average_cpu_percent,
                    "maximum_cpu_percent": observation.maximum_cpu_percent,
                    "sample_count": observation.sample_count,
                    "first_observed_at": observation.first_observed_at.isoformat(),
                    "last_observed_at": observation.last_observed_at.isoformat(),
                    "evidence_ref": observation.evidence_ref,
                    "collection_observed_at": collection.observed_at.isoformat(),
                    "attempt_ref": collection.attempt_ref,
                    "execution_authority": False,
                },
            )
            for index, observation in enumerate(collection.observations, start=1)
        )
        return _table(rows, complete=collection.complete, reason=collection.limitation)

    return evaluate


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = [
    "VM_PROCESS_CPU_FUNCTION_NAME",
    "VmProcessCpuCollection",
    "VmProcessCpuObservation",
    "VmProcessCpuReader",
    "vm_process_cpu_function",
    "vm_process_cpu_function_type",
]
