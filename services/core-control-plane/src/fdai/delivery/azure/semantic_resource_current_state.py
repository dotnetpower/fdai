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
from fdai.shared.providers.state_evidence import STATE_FACT_METADATA_PROPERTY

#: Revision identity exists only for revision-scaled provider types. Every other resource
#: has no revision concept at all, so reporting one would state a gap that cannot exist.
_REVISION_SCALED_TYPES = frozenset({"compute.container-app"})
_REVISION_FIELDS: tuple[tuple[str, str], ...] = (
    ("revision_name", "latestRevisionName"),
    ("ready_revision_name", "latestReadyRevisionName"),
)
_OBSERVABLE_FIELDS: tuple[str, ...] = (
    "provisioning_status",
    "running_status",
    "revision_name",
    "ready_revision_name",
    "source_observed_at",
)


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
        source_fact = _mapping(provider.get(STATE_FACT_METADATA_PROPERTY))
        provisioning_status = _text(state.get("provisioningState"))
        running_status = _text(provider.get("status")) or _text(state.get("runningStatus"))
        values: dict[str, object | None] = {
            "name": _text(target.properties.get("name")),
            "provisioning_status": provisioning_status,
            # The inventory normalizes observed runtime status for every provider type;
            # runningStatus is a revision-scaled field and is absent elsewhere.
            "running_status": running_status,
            "target_state_assessment": _target_state_assessment(
                provisioning_status=provisioning_status,
                running_status=running_status,
            ),
            "assessment_scope": "exact_target_only",
            "related_resources_assessed": False,
            "source_observed_at": _text(source_fact.get("effective_at")),
            "inventory_read_at": secured.receipt.observation_cutoff.isoformat(),
            "execution_authority": False,
        }
        if _models_revisions(target, state):
            for field, provider_key in _REVISION_FIELDS:
                values[field] = _text(state.get(provider_key))
        missing = tuple(
            field for field in _OBSERVABLE_FIELDS if field in values and values[field] is None
        )
        reason = "+".join(f"{field}_unavailable" for field in missing) or None
        return _table(
            (QueryRow.from_values("resource-current-state", values),),
            complete=not missing,
            reason=reason,
        )

    return evaluate


def _models_revisions(target: Any, state: Mapping[str, Any]) -> bool:
    if _text(target.properties.get("type")) in _REVISION_SCALED_TYPES:
        return True
    return any(provider_key in state for _, provider_key in _REVISION_FIELDS)


def _target_state_assessment(
    *,
    provisioning_status: str | None,
    running_status: str | None,
) -> str:
    if provisioning_status == "Succeeded" and running_status == "Running":
        return "observed_running"
    if provisioning_status is not None or running_status is not None:
        return "observed_not_running"
    return "not_proven"


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
