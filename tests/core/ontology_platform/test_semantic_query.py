"""Focused tests for verified query profiles and semantic query receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
    SecuredObjectSetQueryResult,
)
from fdai.core.ontology_platform.query_profiles import QueryProfile
from fdai.core.ontology_platform.semantic_plans import (
    InterpretationCandidateSource,
    SemanticInterpretationCandidate,
    SemanticOperationClass,
    VerifiedInterpretationBasis,
    VerifiedSemanticPlan,
    build_semantic_candidate,
    verify_semantic_candidate,
)
from fdai.core.ontology_platform.semantic_query import (
    SemanticQueryReceipt,
    SemanticQueryService,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    OntologyRelease,
    OntologyTypeRef,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_CATALOG_DIGEST = "sha256:" + "c" * 64


@dataclass(frozen=True, slots=True)
class _Catalog:
    digest: str
    candidate_digest: str

    def contains(self, candidate: SemanticInterpretationCandidate) -> bool:
        return candidate.candidate_digest == self.candidate_digest


@dataclass(frozen=True, slots=True)
class _Harness:
    release: OntologyRelease
    object_type: OntologyObjectType
    function_type: OntologyFunctionType
    profile: QueryProfile
    plan: VerifiedSemanticPlan
    service: SemanticQueryService
    context: FunctionInvocationContext


def _function_type(
    *,
    name: str = "inventory.select_resources",
    kind: OntologyFunctionKind = OntologyFunctionKind.QUERY,
) -> OntologyFunctionType:
    return OntologyFunctionType(
        name=name,
        version="1.0.0",
        kind=kind,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={
            "type": "object",
            "required": ["object_set"],
            "additionalProperties": False,
            "properties": {"object_set": {"type": "object"}},
        },
        output_schema={"type": "object"},
        purpose_bindings=["operations-review"],
    )


def _verified_plan(
    *,
    release: OntologyRelease,
    target_ref: OntologyTypeRef,
    operation_class: SemanticOperationClass,
    arguments: dict[str, Any],
) -> VerifiedSemanticPlan:
    candidate = build_semantic_candidate(
        source=InterpretationCandidateSource.LEXICAL,
        operation_class=operation_class,
        target_ref=target_ref,
        arguments=arguments,
        semantic_catalog_digest=_CATALOG_DIGEST,
        input_text=f"verified {operation_class.value} request",
        score=1.0,
        unresolved_terms=(),
    )
    return verify_semantic_candidate(
        candidate,
        release=release,
        active_semantic_catalog=_Catalog(_CATALOG_DIGEST, candidate.candidate_digest),
        basis=VerifiedInterpretationBasis.EXACT_CATALOG,
        basis_ref=f"catalog:{_CATALOG_DIGEST}",
    )


async def _build_harness(
    *,
    object_ids: tuple[str, ...] = ("resource-a",),
    limit: int = 10,
    extra_function_types: tuple[OntologyFunctionType, ...] = (),
) -> _Harness:
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    function_type = _function_type()
    release = build_ontology_release(
        object_types=(object_type,),
        function_types=(function_type, *extra_function_types),
    )
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=())
    for object_id in object_ids:
        await store.upsert_object(
            OntologyObjectRecord(
                id=object_id,
                object_type="Resource",
                properties={"id": object_id},
            )
        )
    object_sets = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(
            interfaces=(),
            implementations=(),
            object_types=(object_type,),
        ),
        object_type_names=frozenset({"Resource"}),
    )
    gateway = SecuredObjectSetQueryGateway(
        service=object_sets,
        object_types={object_type.name: object_type},
    )
    registry = OntologyFunctionRegistry(release=release)

    async def materialize(arguments: Mapping[str, Any]) -> SecuredObjectSetQueryResult:
        definition = ObjectSetDefinition.model_validate(arguments["object_set"])
        return await gateway.materialize(
            definition,
            projection_request=ProjectionRequest(
                caller_role=CeilingRole.READER,
                declared_purposes=frozenset({definition.purpose}),
            ),
        )

    registry.register(function_type, materialize)
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        purpose="operations-review",
        limit=limit,
    )
    profile = QueryProfile(
        name="inventory.resources",
        version="1.0.0",
        function_type=function_type,
        function_ref=release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            function_type.name,
        ),
        object_set_template=definition,
        purpose="operations-review",
    )
    arguments = {"object_set": definition.model_dump(mode="json")}
    plan = _verified_plan(
        release=release,
        target_ref=profile.function_ref,
        operation_class=SemanticOperationClass.QUERY,
        arguments=arguments,
    )
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        purposes=("operations-review",),
        evidence_refs=("evidence:resource-query",),
    )
    return _Harness(
        release=release,
        object_type=object_type,
        function_type=function_type,
        profile=profile,
        plan=plan,
        service=SemanticQueryService(release=release, registry=registry),
        context=context,
    )


async def test_semantic_query_returns_canonical_object_set_receipt_without_authority() -> None:
    harness = await _build_harness()

    result, receipt = await harness.service.execute(
        profile=harness.profile,
        plan=harness.plan,
        context=harness.context,
    )

    assert isinstance(result, SecuredObjectSetQueryResult)
    assert [item.id for item in result.materialization.graph.objects] == ["resource-a"]
    assert receipt.ontology_release == harness.release.ref()
    assert receipt.profile_ref == harness.profile.profile_ref
    assert receipt.profile_digest == harness.profile.profile_digest
    assert receipt.request_id.startswith("semantic-query-request:")
    assert receipt.plan_digest == harness.plan.plan_digest
    assert receipt.function_invocation.function_ref == harness.profile.function_ref
    assert receipt.function_invocation.purposes == (harness.profile.purpose,)
    assert receipt.truncated is False
    assert receipt.truncation_reason is None
    assert harness.plan.execution_authority is False
    assert receipt.execution_authority is False
    assert receipt.receipt_digest.startswith("sha256:")
    assert SemanticQueryReceipt.model_validate_json(receipt.model_dump_json()) == receipt


async def test_semantic_query_rejects_stale_release() -> None:
    harness = await _build_harness()
    stale_release = build_ontology_release(function_types=(harness.function_type,))
    stale_ref = stale_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        harness.function_type.name,
    )
    stale_profile = harness.profile.model_copy(update={"function_ref": stale_ref})
    stale_plan = _verified_plan(
        release=stale_release,
        target_ref=stale_ref,
        operation_class=SemanticOperationClass.QUERY,
        arguments=harness.plan.arguments,
    )

    with pytest.raises(ValueError, match="stale ontology release"):
        await harness.service.execute(
            profile=stale_profile,
            plan=stale_plan,
            context=harness.context,
        )


async def test_semantic_query_rejects_stale_profile_function_ref() -> None:
    harness = await _build_harness()
    stale_release = build_ontology_release(function_types=(harness.function_type,))
    stale_profile = harness.profile.model_copy(
        update={
            "function_ref": stale_release.type_ref(
                OntologyDeclarationKind.FUNCTION,
                harness.function_type.name,
            )
        }
    )

    with pytest.raises(ValueError, match="stale ontology function"):
        await harness.service.execute(
            profile=stale_profile,
            plan=harness.plan,
            context=harness.context,
        )


async def test_semantic_query_rejects_stale_function_declaration() -> None:
    harness = await _build_harness()
    stale_profile = harness.profile.model_copy(
        update={
            "function_type": harness.function_type.model_copy(
                update={"artifact_digest": "sha256:" + "b" * 64}
            )
        }
    )

    with pytest.raises(ValueError, match="stale ontology function declaration"):
        await harness.service.execute(
            profile=stale_profile,
            plan=harness.plan,
            context=harness.context,
        )


async def test_semantic_query_rejects_mismatched_registry_declaration() -> None:
    harness = await _build_harness()
    registry = OntologyFunctionRegistry(release=harness.release)
    mismatched = harness.function_type.model_copy(update={"artifact_digest": "sha256:" + "b" * 64})

    async def should_not_run(_arguments: Mapping[str, Any]) -> object:
        raise AssertionError("mismatched registry function was invoked")

    with pytest.raises(ValueError, match="does not match release"):
        registry.register(mismatched, should_not_run)


async def test_semantic_query_rejects_registry_release_mismatch() -> None:
    harness = await _build_harness()
    stale_release = build_ontology_release(function_types=(harness.function_type,))
    registry = OntologyFunctionRegistry(release=stale_release)

    async def should_not_run(_arguments: Mapping[str, Any]) -> object:
        raise AssertionError("release-mismatched registry function was invoked")

    registry.register(harness.function_type, should_not_run)
    with pytest.raises(ValueError, match="registry release does not match"):
        SemanticQueryService(release=harness.release, registry=registry)


async def test_semantic_query_rejects_non_query_plan() -> None:
    derive_function = _function_type(
        name="inventory.summarize_resources",
        kind=OntologyFunctionKind.DERIVE,
    )
    harness = await _build_harness(extra_function_types=(derive_function,))
    derive_plan = _verified_plan(
        release=harness.release,
        target_ref=harness.release.type_ref(
            OntologyDeclarationKind.FUNCTION,
            derive_function.name,
        ),
        operation_class=SemanticOperationClass.DERIVE,
        arguments={"object_set": harness.profile.object_set_template.model_dump(mode="json")},
    )

    with pytest.raises(ValueError, match="requires a QUERY plan"):
        await harness.service.execute(
            profile=harness.profile,
            plan=derive_plan,
            context=harness.context,
        )


async def test_semantic_query_rejects_purpose_mismatch() -> None:
    harness = await _build_harness()

    with pytest.raises(PermissionError, match="purpose does not match"):
        await harness.service.execute(
            profile=harness.profile,
            plan=harness.plan,
            context=harness.context.model_copy(update={"purposes": ("incident-review",)}),
        )


async def test_semantic_query_attenuates_extra_purposes_and_stabilizes_request_id() -> None:
    harness = await _build_harness()
    context = harness.context.model_copy(
        update={"purposes": ("operations-review", "incident-review")}
    )

    _first_result, first = await harness.service.execute(
        profile=harness.profile,
        plan=harness.plan,
        context=context,
    )
    _second_result, second = await harness.service.execute(
        profile=harness.profile,
        plan=harness.plan,
        context=context,
    )

    assert first.function_invocation.purposes == ("operations-review",)
    assert first.request_id == second.request_id


async def test_semantic_query_rejects_unsecured_or_wrong_output_type() -> None:
    harness = await _build_harness()
    registry = OntologyFunctionRegistry(release=harness.release)

    async def raw_output(_arguments: Mapping[str, Any]) -> object:
        return {"unsecured": True}

    registry.register(harness.function_type, raw_output)
    service = SemanticQueryService(release=harness.release, registry=registry)

    with pytest.raises(TypeError, match="SecuredObjectSetQueryResult"):
        await service.execute(
            profile=harness.profile,
            plan=harness.plan,
            context=harness.context,
        )


async def test_semantic_query_propagates_object_set_truncation() -> None:
    harness = await _build_harness(object_ids=("resource-a", "resource-b"), limit=1)

    result, receipt = await harness.service.execute(
        profile=harness.profile,
        plan=harness.plan,
        context=harness.context,
    )

    assert isinstance(result, SecuredObjectSetQueryResult)
    assert receipt.truncated is True
    assert receipt.truncation_reason == "result_limit"
