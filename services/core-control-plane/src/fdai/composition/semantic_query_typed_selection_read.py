"""Bind the real pre-Function read stage without allowing network in FunctionRegistry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from fdai_service_contracts.ontology_query import OntologyQueryNode

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.instance_candidate_queries import instance_candidates_function
from fdai.core.ontology_platform.pending_state_coverage import PendingStateCoverageLedger
from fdai.core.ontology_platform.query_execution import QueryNodeHandler, QueryNodeResult
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.ontology_platform.query_source_handlers import FunctionNodeHandler
from fdai.core.ontology_platform.typed_selection_contracts import READ_FUNCTION
from fdai.core.ontology_platform.typed_selection_function import typed_selection_function_type
from fdai.delivery.catalog_search.ontology_governed_selection_read import GovernedTypedSelectionRead
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog


def declare_typed_selection_read(catalog: OntologyCatalog) -> OntologyCatalog:
    declaration = typed_selection_function_type(
        object_type_names=tuple(item.name for item in catalog.object_types)
    )
    existing = next((item for item in catalog.function_types if item.name == READ_FUNCTION), None)
    if existing is not None:
        if existing != declaration:
            raise ValueError("typed selection read declaration conflicts with reviewed source")
        return catalog
    return replace(catalog, function_types=(*catalog.function_types, declaration))


def bind_typed_selection_read(
    registry: OntologyFunctionRegistry,
    catalog: OntologyCatalog,
    reader: GovernedTypedSelectionRead | None,
) -> None:
    if reader is None:
        return
    expected = typed_selection_function_type(
        object_type_names=tuple(item.name for item in catalog.object_types)
    )
    actual = next((item for item in catalog.function_types if item.name == READ_FUNCTION), None)
    if actual != expected:
        raise ValueError("typed selection read binding requires the reviewed declaration")
    registry.register_contextual(
        expected,
        instance_candidates_function(
            reader.consume, ontology_release_digest=registry.release_ref.digest
        ),
    )


def prepared_function_handler(
    registry: OntologyFunctionRegistry,
    context: FunctionInvocationContext,
    reader: GovernedTypedSelectionRead | None,
    *,
    receipt_authority: SecuredQueryReceiptAuthority | None = None,
    pending_state_ledger: PendingStateCoverageLedger | None = None,
) -> QueryNodeHandler:
    def factory(invocation_context: FunctionInvocationContext) -> FunctionNodeHandler:
        return FunctionNodeHandler(
            registry,
            context=invocation_context,
            receipt_authority=receipt_authority,
            allow_presentation_read_dependencies=True,
            pending_state_ledger=pending_state_ledger,
        )

    ordinary = factory(context)

    async def handle(
        node: OntologyQueryNode, dependencies: Mapping[str, QueryNodeResult]
    ) -> QueryNodeResult:
        if node.arguments.get("function_name") != READ_FUNCTION:
            return await ordinary(node, dependencies)
        if reader is None or node.depends_on:
            raise PermissionError(
                "typed selection read stage is unavailable or has unbound dependencies"
            )
        arguments = node.arguments.get("arguments")
        if not isinstance(arguments, dict):
            raise PermissionError("typed selection read stage requires exact typed arguments")
        prepared = await reader.prepare(arguments, context)
        return await factory(prepared)(node, dependencies)

    return handle
