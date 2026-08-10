"""Secured source and typed-function handlers for ontology query plans."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from fdai_service_contracts.ontology_query import OntologyQueryNode

from fdai.shared.contracts.models import CeilingRole, OntologyFunctionKind
from fdai.shared.ontology.acl import ProjectionRequest

from .functions import FunctionInvocationContext, OntologyFunctionRegistry
from .models import ObjectSetDefinition
from .query_execution import QueryNodeResult
from .query_gateway import SecuredObjectSetQueryGateway
from .query_values import QueryRow, QueryTable


class SecuredObjectSetNodeHandler:
    """Materialize one ACL- and purpose-scoped ObjectSet as a bounded table."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        caller_role: CeilingRole,
        purposes: Sequence[str],
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
        )

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if dependencies:
            raise ValueError("object_set node MUST NOT consume dependency results")
        definition = ObjectSetDefinition.model_validate(node.arguments.get("definition"))
        secured = await self._gateway.materialize(
            definition,
            projection_request=self._request,
        )
        table = QueryTable(
            rows=tuple(
                QueryRow.from_values(
                    record.id,
                    {
                        "id": record.id,
                        "object_type": record.object_type,
                        "properties": record.properties,
                    },
                )
                for record in secured.materialization.graph.objects
            ),
            complete=secured.receipt.complete,
            truncation_reason=(
                secured.receipt.truncation_reason.value
                if secured.receipt.truncation_reason is not None
                else None
            ),
        )
        return QueryNodeResult(
            value=table,
            evidence_refs=(
                f"ontology-object-set:{secured.receipt.projected_result_digest}",
                f"ontology-query-table:{table.digest}",
            ),
        )


class FunctionNodeHandler:
    """Invoke one exact-release query, derive, or validate function with a receipt."""

    def __init__(
        self,
        registry: OntologyFunctionRegistry,
        *,
        context: FunctionInvocationContext,
    ) -> None:
        self._registry = registry
        self._context = context

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        function_name = node.arguments.get("function_name")
        if not isinstance(function_name, str):
            raise ValueError("function node requires function_name")
        declaration = self._registry.declaration(function_name)
        if declaration.kind is OntologyFunctionKind.PLAN:
            raise PermissionError("query plan MUST NOT invoke plan functions")
        raw_arguments = node.arguments.get("arguments", {})
        if not isinstance(raw_arguments, dict):
            raise ValueError("function arguments MUST be an object")
        arguments = dict(raw_arguments)
        raw_bindings = node.arguments.get("dependency_arguments", {})
        if not isinstance(raw_bindings, dict):
            raise ValueError("function dependency_arguments MUST be an object")
        if set(raw_bindings) != set(node.depends_on):
            raise ValueError("function dependency arguments MUST bind every dependency")
        for dependency_id, argument_name_raw in raw_bindings.items():
            argument_name = _argument_name(argument_name_raw)
            if argument_name in arguments:
                raise ValueError("function dependency argument collides with static argument")
            arguments[argument_name] = _function_value(dependencies[dependency_id].value)
        result, receipt = await self._registry.invoke_with_receipt(
            function_name,
            arguments,
            context=self._context,
        )
        return QueryNodeResult(
            value=result,
            evidence_refs=_evidence_refs(dependencies)
            + (f"ontology-function:{receipt.invocation_id}",),
        )


def _argument_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("function argument name MUST contain between 1 and 256 characters")
    parts = value.split(".")
    if any(not part or not part.replace("_", "").replace("-", "").isalnum() for part in parts):
        raise ValueError("function argument name MUST be a dot-separated identifier")
    return value


def _function_value(value: object) -> object:
    if isinstance(value, QueryTable):
        return json.loads(value.canonical_json())
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _evidence_refs(dependencies: Mapping[str, QueryNodeResult]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            evidence_ref
            for result in dependencies.values()
            for evidence_ref in result.evidence_refs
        )
    )


__all__ = ["FunctionNodeHandler", "SecuredObjectSetNodeHandler"]
