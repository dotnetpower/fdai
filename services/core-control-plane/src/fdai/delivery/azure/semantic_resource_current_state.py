"""Project exact Azure Resource inventory state into generic verified fields."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.resource_current_state_queries import (
    RESOURCE_CURRENT_STATE_FUNCTION_NAME,
)
from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyRelease


def semantic_resource_current_state_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Return bounded current-state fields from one exact secured Resource."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_CURRENT_STATE_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError(
                "resource current-state purpose does not match invocation context"
            )
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        objects = secured.materialization.graph.objects
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="target_resolution_incomplete")
        if len(objects) != 1:
            return _table((), complete=False, reason="target_resolution_not_exact")
        target = objects[0]
        provider = _mapping(target.properties.get("properties"))
        state = _mapping(provider.get("properties"))
        source_fact = _mapping(provider.get("_state_fact"))
        values = {
            "name": _text(target.properties.get("name")),
            "revision_name": _text(state.get("latestRevisionName")),
            "ready_revision_name": _text(state.get("latestReadyRevisionName")),
            "provisioning_status": _text(state.get("provisioningState")),
            "running_status": _text(state.get("runningStatus")),
            "source_observed_at": _text(source_fact.get("effective_at")),
            "inventory_read_at": secured.receipt.observation_cutoff.isoformat(),
            "execution_authority": False,
        }
        missing = tuple(
            field
            for field in (
                "revision_name",
                "ready_revision_name",
                "source_observed_at",
            )
            if values[field] is None
        )
        reason = "+".join(f"{field}_unavailable" for field in missing) or None
        return _table(
            (QueryRow.from_values("resource-current-state", values),),
            complete=not missing,
            reason=reason,
        )

    return evaluate


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = ["semantic_resource_current_state_function"]
