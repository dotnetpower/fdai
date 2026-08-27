"""Exact-release FunctionType for bounded Kubernetes Pod diagnosis evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
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
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .kubernetes_pod_diagnosis_evidence import (
    ContainerTerminationEvidence,
    KubernetesPodLogEvidence,
    assess_kubernetes_pod_diagnosis,
)

KUBERNETES_POD_DIAGNOSIS_FUNCTION_NAME = "query.kubernetes_pod_diagnosis"
_PURPOSE = "operations-review"


class KubernetesPodLogEvidenceReader(Protocol):
    """Read content-free runtime log evidence for one exact Pod UID."""

    async def collect(
        self,
        *,
        pod_uid: str,
        start: datetime,
        end: datetime,
    ) -> KubernetesPodLogEvidence: ...


def _source_artifact_digest() -> str:
    source = Path(__file__).read_bytes()
    reducer = Path(__file__).with_name("kubernetes_pod_diagnosis_evidence.py").read_bytes()
    return f"sha256:{hashlib.sha256(source + b'\0' + reducer).hexdigest()}"


def kubernetes_pod_diagnosis_function_type() -> OntologyFunctionType:
    """Declare one read-only exact-Pod diagnosis function."""

    return OntologyFunctionType(
        name=KUBERNETES_POD_DIAGNOSIS_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["pod_query_result", "lifecycle_events", "lookback_seconds"],
            "properties": {
                "pod_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "lifecycle_events": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "lookback_seconds": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 86_400,
                },
                "container_name": {"type": "string", "minLength": 1, "maxLength": 512},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": 1},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[_PURPOSE],
        timeout_seconds=30,
        cpu_millis=500,
        memory_bytes=67_108_864,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def kubernetes_pod_diagnosis_function(
    ontology_release: OntologyRelease,
    *,
    log_reader: KubernetesPodLogEvidenceReader,
) -> ContextualOntologyFunction:
    """Bind exact secured Pod state to bounded content-free runtime logs."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        KUBERNETES_POD_DIAGNOSIS_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (_PURPOSE,):
            raise PermissionError("Kubernetes Pod diagnosis purpose does not match")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["pod_query_result"])
        if (
            not secured.receipt.complete
            or secured.receipt.truncated
            or secured.materialization.graph.truncated
        ):
            return _table((), complete=False, reason="pod_scope_incomplete")
        objects = secured.materialization.graph.objects
        if len(objects) != 1 or _resource_type(objects[0]) != "kubernetes.pod":
            return _table((), complete=False, reason="pod_target_not_exact")
        pod = objects[0]
        properties = _resource_properties(pod)
        pod_uid = _required_text(properties, "uid")
        cutoff = secured.receipt.observation_cutoff
        lookback_seconds = int(arguments["lookback_seconds"])
        start = cutoff - timedelta(seconds=lookback_seconds)
        lifecycle_events = _query_table(arguments["lifecycle_events"])
        termination = _termination_evidence(
            properties=properties,
            lifecycle_events=lifecycle_events,
            container_name=arguments.get("container_name"),
            pod_evidence_ref=secured.receipt.projected_result_digest,
        )
        logs = await log_reader.collect(pod_uid=pod_uid, start=start, end=cutoff)
        result = assess_kubernetes_pod_diagnosis(
            pod_uid=pod_uid,
            termination=termination,
            logs=logs,
            cutoff=cutoff,
        )
        if not lifecycle_events.complete:
            result = result.model_copy(
                update={
                    "complete": False,
                    "evidence_gaps": tuple(
                        dict.fromkeys(
                            (
                                *result.evidence_gaps,
                                "lifecycle_events_"
                                f"{lifecycle_events.truncation_reason or 'incomplete'}",
                            )
                        )
                    ),
                }
            )
        values = result.model_dump(mode="json")
        return _table(
            (QueryRow.from_values("kubernetes-pod-diagnosis", values),),
            complete=result.complete,
            reason=None if result.complete else "+".join(result.evidence_gaps),
        )

    return evaluate


def _termination_evidence(
    *,
    properties: Mapping[str, Any],
    lifecycle_events: QueryTable,
    container_name: object,
    pod_evidence_ref: str,
) -> ContainerTerminationEvidence | None:
    requested_container = (
        container_name.strip()
        if isinstance(container_name, str) and container_name.strip()
        else None
    )
    raw = properties.get("container_terminations", ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("Pod container_terminations MUST be a sequence")
    candidates: list[tuple[datetime, Mapping[str, Any]]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("Pod container termination record MUST be an object")
        item_name = _required_text(item, "container_name")
        if requested_container is not None and item_name != requested_container:
            continue
        finished_at = _optional_time(item, "finished_at")
        if finished_at is None:
            continue
        candidates.append((finished_at, item))
    if not candidates:
        return None
    latest = max(item[0] for item in candidates)
    selected = [item for finished_at, item in candidates if finished_at == latest]
    if len(selected) != 1:
        raise ValueError("Pod container termination selection is ambiguous")
    item = selected[0]
    lifecycle_reasons = tuple(
        dict.fromkeys(
            str(row.values["event_kind"])
            for row in lifecycle_events.rows
            if isinstance(row.values.get("event_kind"), str)
        )
    )
    evidence_refs = tuple(
        dict.fromkeys(
            (
                pod_evidence_ref,
                *(
                    str(row.values["evidence_ref"])
                    for row in lifecycle_events.rows
                    if isinstance(row.values.get("evidence_ref"), str)
                ),
            )
        )
    )
    return ContainerTerminationEvidence(
        pod_uid=_required_text(properties, "uid"),
        container_name=_required_text(item, "container_name"),
        reason=_optional_text(item, "reason"),
        exit_code=_required_int(item, "exit_code"),
        signal=_optional_int(item, "signal"),
        finished_at=_optional_time(item, "finished_at"),
        lifecycle_reasons=lifecycle_reasons,
        evidence_refs=evidence_refs,
    )


def _resource_type(record: OntologyObjectRecord) -> str | None:
    value = record.properties.get("type")
    return value if isinstance(value, str) else None


def _resource_properties(record: OntologyObjectRecord) -> Mapping[str, Any]:
    value = record.properties.get("properties")
    if not isinstance(value, Mapping):
        raise ValueError("Pod Resource properties are unavailable")
    return value


def _query_table(value: object) -> QueryTable:
    if not isinstance(value, Mapping):
        raise ValueError("lifecycle_events MUST be a query table")
    raw_rows = value.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("lifecycle_events rows MUST be a sequence")
    rows = []
    for item in raw_rows:
        if not isinstance(item, Mapping):
            raise ValueError("lifecycle event row MUST be an object")
        rows.append(
            QueryRow.from_values(
                _required_text(item, "row_id"),
                item.get("values"),
            )
        )
    complete = value.get("complete")
    reason = value.get("truncation_reason")
    if not isinstance(complete, bool) or (reason is not None and not isinstance(reason, str)):
        raise ValueError("lifecycle_events completeness is invalid")
    return QueryTable(rows=tuple(rows), complete=complete, truncation_reason=reason)


def _required_text(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip() or len(result) > 512:
        raise ValueError(f"{key} MUST be bounded non-empty text")
    return result.strip()


def _optional_text(value: Mapping[str, Any], key: str) -> str | None:
    result = value.get(key)
    if result is None:
        return None
    if not isinstance(result, str) or not result.strip() or len(result) > 512:
        raise ValueError(f"{key} MUST be bounded non-empty text or null")
    return result.strip()


def _required_int(value: Mapping[str, Any], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        raise ValueError(f"{key} MUST be a non-negative integer")
    return result


def _optional_int(value: Mapping[str, Any], key: str) -> int | None:
    if key not in value:
        return None
    return _required_int(value, key)


def _optional_time(value: Mapping[str, Any], key: str) -> datetime | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{key} MUST be an ISO timestamp or null")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{key} MUST be an ISO timestamp or null") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{key} MUST include timezone")
    return parsed


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = [
    "KUBERNETES_POD_DIAGNOSIS_FUNCTION_NAME",
    "KubernetesPodLogEvidenceReader",
    "kubernetes_pod_diagnosis_function",
    "kubernetes_pod_diagnosis_function_type",
]
