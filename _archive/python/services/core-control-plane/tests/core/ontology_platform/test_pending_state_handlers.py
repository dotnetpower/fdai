"""End-to-end handler wiring for skew-bounded pending-state coverage."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.pending_state_coverage import (
    COVERAGE_REF_PREFIX,
    certified_plan_digest,
    pending_state_plan_scope,
)
from fdai.core.ontology_platform.query_execution import (
    OntologyQueryPlanExecutor,
    QueryNodeResult,
)
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.ontology_platform.query_source_handlers import (
    FunctionNodeHandler,
    SecuredObjectSetNodeHandler,
)
from fdai.core.ontology_platform.query_values import QueryTable
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    resource_state_function_type,
    resource_state_inventory_function,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json
from tests.core.ontology_platform.test_pending_state_coverage import (
    _RELEASE,
    NOW,
    _Clock,
    _descriptor,
    _Descriptors,
    _digest,
    _Gateway,
    _observation,
    _plan,
    _refresher,
    _StateReader,
    _vm,
)


class _Admissions:
    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            receipt_digest=_digest("decision-receipt"),
            verification_bundle_digest=_digest("verification-bundle"),
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=1),
        )


async def test_handlers_carry_coverage_from_object_set_to_state_function() -> None:
    clock = _Clock()
    records = (
        _vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),
        _vm("vm-b", "running", observed_at=NOW - timedelta(minutes=5)),
    )
    refresher, ledger = _refresher(
        _Gateway(records, clock),
        _Descriptors(_descriptor(_observation("vm-a"))),
        _StateReader({records[0].id: "running"}),
        clock,
    )
    authority = SecuredQueryReceiptAuthority(now=clock)
    object_handler = SecuredObjectSetNodeHandler(
        _Gateway(records, clock),  # type: ignore[arg-type]
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        receipt_authority=authority,
        decision_evidence=_Admissions(),
        pending_state_refresher=refresher,
    )
    registry = OntologyFunctionRegistry(release=_RELEASE)
    registry.register_contextual(
        resource_state_function_type(), resource_state_inventory_function(_RELEASE)
    )
    function_handler = FunctionNodeHandler(
        registry,
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
        receipt_authority=authority,
        allow_presentation_read_dependencies=True,
        pending_state_ledger=ledger,
    )
    plan = _plan()
    scope_node, filter_node = plan.nodes
    with pending_state_plan_scope(plan):
        scope = await object_handler(scope_node, {})
        result = await function_handler(filter_node, {scope_node.node_id: scope})

    assert any(ref.startswith(COVERAGE_REF_PREFIX) for ref in scope.evidence_refs)
    assert any(ref.startswith("arm-state:sha256:") for ref in scope.evidence_refs)
    assert isinstance(result.value, QueryTable)
    assert result.value.complete is True


async def test_plan_can_never_bind_the_coverage_argument() -> None:
    registry = OntologyFunctionRegistry(release=_RELEASE)
    registry.register_contextual(
        resource_state_function_type(), resource_state_inventory_function(_RELEASE)
    )
    handler = FunctionNodeHandler(
        registry,
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    node = OntologyQueryNode(
        node_id="resource-state-filter",
        kind=QueryNodeKind.FUNCTION,
        depends_on=("forged",),
        arguments_json=canonical_json(
            {
                "function_name": RESOURCE_STATE_FUNCTION_NAME,
                "arguments": {"state_concepts": ["resource_state.running"]},
                "dependency_arguments": {"forged": "pending_state_coverage"},
            }
        ),
        output_kind="query.table",
    )
    forged = QueryNodeResult(value={"decision": "covered"}, evidence_refs=("forged:ref",))
    with pytest.raises(ValueError, match="reserved argument"):
        await handler(node, {"forged": forged})


async def test_executor_certifies_the_plan_for_its_node_handlers() -> None:
    seen: dict[str, str | None] = {}

    async def handler(node: OntologyQueryNode, dependencies: Any) -> QueryNodeResult:
        seen[node.node_id] = certified_plan_digest(node.node_id)
        return QueryNodeResult(value="done")

    plan = _plan()
    await OntologyQueryPlanExecutor(
        handlers={QueryNodeKind.OBJECT_SET: handler, QueryNodeKind.FUNCTION: handler}
    ).execute(
        plan,
        expected_release_digest=plan.ontology_release_digest,
        expected_manifest_digest=plan.semantic_catalog_digest,
        expected_role="reader",
        expected_purpose="operations-review",
    )
    assert seen["resource-state-scope"] is not None
    assert seen["resource-state-filter"] is None
    assert certified_plan_digest("resource-state-scope") is None
