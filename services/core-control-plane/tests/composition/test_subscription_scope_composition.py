"""Production semantic composition for current-subscription identity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.composition import build_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import QueryTable
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.subscription_scope_queries import (
    SUBSCRIPTION_SCOPE_FUNCTION_NAME,
    SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS,
    SubscriptionScopeCollection,
    SubscriptionScopeObservation,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai_service_contracts.ontology_query import EvidenceAuthority, TaskStatus

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


class _Model:
    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "select",
            "subject_constraints": ["current Azure subscription"],
            "measure_concepts": list(SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS),
            "temporal_scope": {},
            "output_shape": "subscription_scope_identity",
            "evidence_requirements": [SUBSCRIPTION_SCOPE_FUNCTION_NAME],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.98,
        }

    def propose_plan(self, **_kwargs: Any) -> None:
        return None


class _Reader:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    async def read(self) -> SubscriptionScopeCollection:
        if not self.available:
            return SubscriptionScopeCollection(
                observation=None,
                observed_at=NOW,
                complete=False,
                limitation="source_unavailable",
                attempt_ref="sha256:" + ("b" * 64),
            )
        return SubscriptionScopeCollection(
            observation=SubscriptionScopeObservation(
                display_name="Example subscription",
                state="Enabled",
                masked_subscription_id="0000...0000",
                observed_at=NOW,
                evidence_digest=DIGEST,
            ),
            observed_at=NOW,
            complete=True,
            limitation=None,
            attempt_ref="sha256:" + ("b" * 64),
        )


def _object_type() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )


def _catalog(object_type: OntologyObjectType) -> OntologyCatalog:
    return OntologyCatalog(
        object_types=(object_type,),
        interface_types=(),
        interface_implementations=(),
        link_types=(),
        action_types=(),
        property_semantics=empty_property_semantic_registry(),
    )


async def test_runtime_registers_and_executes_subscription_scope_with_exact_authority() -> None:
    object_type = _object_type()
    function_types = operational_function_types(())
    runtime = build_semantic_query_runtime(
        model=_Model(),
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            function_types=function_types,
        ),
        ontology_catalog=_catalog(object_type),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(object_type,),
            link_types=(),
        ),
        subscription_scope_reader=_Reader(),
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="meaning is supplied by the model frame",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert runtime.function_bindings[SUBSCRIPTION_SCOPE_FUNCTION_NAME] is (
        EvidenceAuthority.SERVER_SUBSCRIPTION_SCOPE
    )
    assert result.disposition == "answered"
    assert result.execution is not None
    task = result.execution.results["subscription-scope-identity"]
    assert task.evidence_refs
    assert result.execution.receipts[0].status is TaskStatus.COMPLETED
    assert result.execution.receipts[0].authority is EvidenceAuthority.SERVER_SUBSCRIPTION_SCOPE


async def test_runtime_preserves_explicit_unavailable_subscription_evidence() -> None:
    object_type = _object_type()
    function_types = operational_function_types(())
    runtime = build_semantic_query_runtime(
        model=_Model(),
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            function_types=function_types,
        ),
        ontology_catalog=_catalog(object_type),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(object_type,),
            link_types=(),
        ),
        subscription_scope_reader=_Reader(available=False),
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance="meaning is supplied by the model frame",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.execution is not None
    table = result.execution.results["subscription-scope-identity"].value
    assert isinstance(table, QueryTable)
    assert table.rows == ()
    assert table.complete is False
    assert table.truncation_reason == "source_unavailable"
