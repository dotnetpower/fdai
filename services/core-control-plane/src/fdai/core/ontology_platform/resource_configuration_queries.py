"""Read-only configuration comparison over currently authorized Resources and retained views."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .query_gateway import SecuredObjectSetQueryResult
from .query_values import QueryRow, QueryTable
from .resource_configuration_snapshots import (
    MAX_CONFIGURATION_RESOURCES,
    MAX_CONFIGURATION_WINDOW_SECONDS,
    ScopedConfigurationRecord,
    ScopedConfigurationSnapshot,
    authorized_configuration_scope,
    configuration_scope_digest,
    configuration_scope_reason,
    configuration_timestamp,
)

RESOURCE_CONFIGURATION_FUNCTION_NAME = "query.resource_configuration_changes"


def resource_configuration_function_type() -> OntologyFunctionType:
    """Declare a bounded pure comparison; all source views must arrive as DAG dependencies."""
    projection = Path(__file__).with_name("resource_configuration_projection.py")
    snapshots = Path(__file__).with_name("resource_configuration_snapshots.py")
    return OntologyFunctionType(
        name=RESOURCE_CONFIGURATION_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:"
        + hashlib.sha256(
            Path(__file__).read_bytes() + projection.read_bytes() + snapshots.read_bytes()
        ).hexdigest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "query_result",
                "before_snapshot",
                "after_snapshot",
                "before_as_of",
                "after_as_of",
                "known_at",
            ],
            "properties": {
                **{
                    name: {"type": "object", "x-fdai-dependency-only": True}
                    for name in ("query_result", "before_snapshot", "after_snapshot")
                },
                **{
                    name: {"type": "string", "format": "date-time"}
                    for name in ("before_as_of", "after_as_of", "known_at")
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": MAX_CONFIGURATION_RESOURCES},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=10,
        cpu_millis=500,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_configuration_changes_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Consume issued current scope and two already-scoped snapshots without provider I/O."""
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION, RESOURCE_CONFIGURATION_FUNCTION_NAME
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        context: FunctionInvocationContext,
    ) -> object:
        before_as_of = configuration_timestamp(arguments["before_as_of"])
        after_as_of = configuration_timestamp(arguments["after_as_of"])
        known_at = configuration_timestamp(arguments["known_at"])
        _verify_times(before_as_of, after_as_of, known_at)
        secured = authorized_configuration_scope(
            arguments["query_result"],
            context,
            ontology_release,
            known_at=known_at,
        )
        before = ScopedConfigurationSnapshot.model_validate(arguments["before_snapshot"])
        after = ScopedConfigurationSnapshot.model_validate(arguments["after_snapshot"])
        for view, expected in ((before, before_as_of), (after, after_as_of)):
            if view.as_of != expected or view.known_at != known_at:
                raise ValueError("configuration history changed the requested time boundary")
        return compare_resource_configuration(
            query_result=secured,
            before=before,
            after=after,
        )

    return evaluate


def compare_resource_configuration(
    *,
    query_result: SecuredObjectSetQueryResult,
    before: ScopedConfigurationSnapshot,
    after: ScopedConfigurationSnapshot,
) -> dict[str, Any]:
    """Compare reviewed fields only for selected IDs; incomplete evidence cannot prove no change."""
    _verify_times(before.as_of, after.as_of, after.known_at)
    if before.known_at != after.known_at:
        raise ValueError("configuration views MUST share one knowledge cutoff")
    scope_reason = configuration_scope_reason(query_result)
    if scope_reason is not None:
        return _table((), reason=scope_reason)
    selected = tuple(sorted(query_result.materialization.graph.objects, key=lambda item: item.id))
    allowed = {item.id for item in selected}
    scope_digest = configuration_scope_digest(query_result)
    for snapshot in (before, after):
        if snapshot.scope_receipt_digest != scope_digest or any(
            item.resource_id not in allowed for item in snapshot.records
        ):
            raise PermissionError("configuration snapshot does not match the current issued scope")
    before_records = {item.resource_id: item for item in before.records}
    after_records = {item.resource_id: item for item in after.records}
    rows: list[QueryRow] = []
    reasons: list[str] = []
    for target in selected:
        reason: str | None = None
        if not before.complete or not after.complete:
            reason = before.reason or after.reason or "configuration_history_incomplete"
        elif target.id not in before_records:
            reason = "configuration_baseline_missing"
        elif target.id not in after_records:
            reason = "configuration_after_missing"
        values = _comparison(
            target, before_records.get(target.id), after_records.get(target.id), reason=reason
        )
        if values["reason"] is not None:
            reasons.append(values["reason"])
        evidence_refs = [f"ontology-object-set:{query_result.receipt.projected_result_digest}"]
        evidence_refs.extend(
            (
                f"configuration-before-snapshot:{before.digest}",
                f"configuration-after-snapshot:{after.digest}",
            )
        )
        for label in ("before", "after"):
            if values[f"{label}_digest"] is not None:
                evidence_refs.append(f"configuration-{label}:{values[f'{label}_digest']}")
        values.update(
            before_as_of=before.as_of.isoformat(),
            after_as_of=after.as_of.isoformat(),
            known_at=after.known_at.isoformat(),
            evidence_refs=evidence_refs,
        )
        rows.append(QueryRow.from_values(target.id, values))
    if not selected and (not before.complete or not after.complete):
        reasons.append(before.reason or after.reason or "configuration_history_incomplete")
    return _table(tuple(rows), reason=sorted(set(reasons))[0] if reasons else None)


def _comparison(
    target: OntologyObjectRecord,
    before: ScopedConfigurationRecord | None,
    after: ScopedConfigurationRecord | None,
    *,
    reason: str | None,
) -> dict[str, Any]:
    expected_type = target.properties.get("type")
    if (
        not isinstance(expected_type, str)
        or not expected_type.strip()
        or any(
            record is not None and record.resource_type != expected_type
            for record in (before, after)
        )
    ):
        before = after = None
        reason = "configuration_identity_mismatch"
    old = before.projection if before else None
    new = after.projection if after else None
    fields = sorted(set(old.values if old else ()) | set(new.values if new else ()))
    model = expected_type == "llm-model-deployment"
    if not model:
        fields = [
            field
            for field in fields
            if (old is not None and old.values.get(field) is not None)
            or (new is not None and new.values.get(field) is not None)
        ]
    missing = [
        field
        for field in fields
        if old is None
        or new is None
        or old.values.get(field) is None
        or new.values.get(field) is None
    ]
    changed = [
        field
        for field in fields
        if field not in missing
        and old is not None
        and new is not None
        and old.values[field] != new.values[field]
    ]
    if reason is None and (not fields or missing):
        reason = "configuration_fields_unavailable"
    return {
        "resource_id": target.id,
        "name": target.properties.get("name"),
        "type": expected_type,
        "comparison_status": "unknown"
        if reason
        else ("changed" if changed else "unchanged_reviewed_fields"),
        "reason": reason,
        "coverage": "reviewed_fields_only",
        "changed_fields": changed,
        "missing_fields": missing,
        "before": dict(old.values) if old else None,
        "after": dict(new.values) if new else None,
        "before_digest": old.digest if old else None,
        "after_digest": new.digest if new else None,
        "capacity_semantics": "capacity_units_is_desired; current_capacity_units_is_observed",
        "potential_implications": (
            [
                "Model, SKU, or capacity changes may affect throttling or latency "
                "if demand exceeds "
                "the effective deployment limit; configuration alone cannot establish an observed "
                "effect."
            ]
            if model and changed
            else []
        ),
        "observed_429": "unknown",
        "observed_500": "unknown",
        "observed_latency_effect": "unknown",
        "causal_claim_supported": False,
        "execution_authority": False,
    }


def _verify_times(before: datetime, after: datetime, known: datetime) -> None:
    if any(item.tzinfo is None for item in (before, after, known)):
        raise ValueError("configuration times MUST be timezone-aware")
    if (
        not before < after <= known
        or (after - before).total_seconds() > MAX_CONFIGURATION_WINDOW_SECONDS
    ):
        raise ValueError("configuration comparison requires an ordered bounded historical window")


def _table(rows: tuple[QueryRow, ...], *, reason: str | None) -> dict[str, Any]:
    table = QueryTable(rows=rows, complete=reason is None, truncation_reason=reason)
    return cast(dict[str, Any], json.loads(table.canonical_json()))


__all__ = [
    "MAX_CONFIGURATION_RESOURCES",
    "MAX_CONFIGURATION_WINDOW_SECONDS",
    "RESOURCE_CONFIGURATION_FUNCTION_NAME",
    "compare_resource_configuration",
    "resource_configuration_changes_function",
    "resource_configuration_function_type",
]
