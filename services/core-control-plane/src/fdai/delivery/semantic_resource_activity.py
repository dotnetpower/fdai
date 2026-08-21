"""Bind exact ontology targets to the existing resource activity investigation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
)
from fdai.core.read_investigation import (
    ReadInvestigationBudget,
    ReadInvestigationRequest,
    ReadInvestigationService,
    plan_read_investigation,
)
from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyRelease
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ReadInvestigationProvider,
    ReadToolId,
    ResourceSelector,
)


def semantic_resource_activity_function(
    ontology_release: OntologyRelease,
    *,
    provider: ReadInvestigationProvider,
) -> ContextualOntologyFunction:
    """Run one bounded change-history request from an exact secured ObjectSet."""
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_ACTIVITY_FUNCTION_NAME,
    )
    service = ReadInvestigationService(provider)

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("resource activity purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        objects = secured.materialization.graph.objects
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="target_resolution_incomplete")
        if len(objects) != 1:
            return _table((), complete=False, reason="target_resolution_not_exact")
        target = objects[0]
        name = _property_text(target.properties, "name")
        if name is None:
            return _table((), complete=False, reason="target_name_unavailable")
        group = _resource_group(target.id, target.properties)
        lookback_seconds = int(arguments["lookback_seconds"])
        identity = content_digest(
            {
                "target": target.id,
                "cutoff": secured.receipt.observation_cutoff.isoformat(),
                "lookback_seconds": lookback_seconds,
            }
        )
        request = ReadInvestigationRequest(
            requester_ref=f"semantic:{identity[7:31]}",
            conversation_ref=f"semantic:{identity[31:55]}",
            correlation_ref=f"semantic:{identity[55:71]}",
            intent=ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
            selector=ResourceSelector(
                name=name,
                scope_ref=secured.receipt.projected_result_digest,
                resource_group=group,
            ),
            lookback_seconds=lookback_seconds,
            requested_evidence=(ReadToolId.QUERY_RESOURCE_ACTIVITY,),
            budget=ReadInvestigationBudget(
                max_wall_seconds=15,
                max_tool_calls=2,
                max_results=32,
                max_output_bytes=262_144,
            ),
            idempotency_key=f"semantic-activity:{identity[7:39]}",
            created_at=datetime.now(UTC),
        )
        result = await service.execute(plan_read_investigation(request))
        rows: list[QueryRow] = []
        limitations: list[str] = []
        for envelope in result.evidence:
            limitations.extend(item.value for item in envelope.limitations)
            for index, record in enumerate(envelope.records):
                rows.append(
                    QueryRow.from_values(
                        f"activity-{index + 1}",
                        {
                            "occurred_at": record.occurred_at.isoformat(),
                            "operation": record.operation_kind,
                            "status": record.status,
                            "actor_kind": (
                                record.actor_kind.value if record.actor_kind is not None else None
                            ),
                            "actor_ref": record.actor_ref,
                            "correlation_ref": record.correlation_ref,
                            "freshness": envelope.freshness.value,
                            "authority": envelope.authority,
                            "evidence_refs": list(envelope.evidence_refs),
                            "limitations": [item.value for item in envelope.limitations],
                            "execution_authority": False,
                        },
                    )
                )
        complete = result.outcome.value in {"matched", "none"} and not limitations
        reason = None if complete else "+".join(dict.fromkeys(limitations)) or result.outcome.value
        return _table(tuple(rows), complete=complete, reason=reason)

    return evaluate


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


def _property_text(properties: Mapping[str, Any], key: str) -> str | None:
    value = properties.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _resource_group(resource_id: str, properties: Mapping[str, Any]) -> str | None:
    for key in ("resource_group", "resourceGroup"):
        value = _property_text(properties, key)
        if value is not None:
            return value
    parts = resource_id.split("/")
    folded = [part.casefold() for part in parts]
    if "resource-group" in folded:
        index = folded.index("resource-group") + 1
        return parts[index] if index < len(parts) and parts[index] else None
    if "resourcegroups" in folded:
        index = folded.index("resourcegroups") + 1
        return parts[index] if index < len(parts) and parts[index] else None
    return None


__all__ = ["semantic_resource_activity_function"]
