"""Kinetic ontology safety tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.ontology_platform import (
    AuthorityClass,
    CriterionResult,
    MutationEffect,
    MutationEffectKind,
    OntologyFunctionKind,
    OntologyFunctionRegistry,
    OntologyFunctionType,
    ProjectionBinding,
    ReconciliationStatus,
    build_mutation_plan,
    project_source_records,
    reconcile_expected_effects,
    validate_plan_revisions,
)
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyObjectType,
    Operation,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    RollbackKind,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


async def _fixture():
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "replicas": PropertyDecl(type=PropertyType.INTEGER, required=True),
        },
    )
    action_type = OntologyActionType(
        schema_version="1.0.0",
        name="ops.scale",
        version="1.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=1.0, max_policy_escapes=0
        ),
    )
    release = build_ontology_release(object_types=(object_type,), action_types=(action_type,))
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=())
    target = await store.upsert_object(
        OntologyObjectRecord(
            id="workload-a",
            object_type="Workload",
            properties={"id": "workload-a", "replicas": 2},
        )
    )
    return release, target


async def test_mutation_plan_is_digest_stable_and_rejects_stale_revision() -> None:
    release, target = await _fixture()
    expected = MutationEffect(
        kind=MutationEffectKind.EXPECTED_PROPERTY,
        target_id=target.id,
        property_name="replicas",
        value=3,
    )
    command = MutationEffect(
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target.id,
        command_ref="provider.scale",
    )
    rollback = MutationEffect(
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target.id,
        command_ref="provider.scale.rollback",
    )
    values = dict(
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale"),
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=(expected,),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        max_affected_objects=1,
    )

    plan = build_mutation_plan(**values)
    replay = build_mutation_plan(**values)

    assert plan.digest == replay.digest
    validate_plan_revisions(plan, {target.id: target})
    with pytest.raises(ValueError, match="stale"):
        validate_plan_revisions(plan, {target.id: replace(target, revision=2)})


async def test_typed_functions_cannot_return_plan_from_read_kind() -> None:
    registry = OntologyFunctionRegistry()
    declaration = OntologyFunctionType(
        name="query.workloads",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

    async def query(_arguments):
        return {"count": 1}

    registry.register(declaration, query)
    assert await registry.invoke("query.workloads", {}) == {"count": 1}

    validate_decl = declaration.model_copy(
        update={"name": "validate.workload", "kind": OntologyFunctionKind.VALIDATE}
    )

    async def validate(_arguments):
        return CriterionResult(passed=True, reason_code="ready", evidence_refs=("object:x",))

    registry.register(validate_decl, validate)
    result = await registry.invoke("validate.workload", {})
    assert isinstance(result, CriterionResult)


async def test_projection_binding_pins_release_and_watermark() -> None:
    release, _target = await _fixture()
    binding = ProjectionBinding(
        binding_id="inventory.workload",
        source_id="inventory",
        object_type_ref=release.type_ref(OntologyDeclarationKind.OBJECT, "Workload"),
        authority_class=AuthorityClass.PROVIDER_OBSERVED,
        identity_field="resource_id",
        property_map={"resource_id": "id", "replica_count": "replicas"},
        watermark_field="observed_at",
    )

    records, watermark = project_source_records(
        binding=binding,
        records=(
            {
                "resource_id": "workload-a",
                "replica_count": 2,
                "observed_at": "2026-08-01T00:00:00Z",
            },
        ),
        release=release,
    )

    assert records[0].type_ref == binding.object_type_ref
    assert records[0].properties == {"id": "workload-a", "replicas": 2}
    assert watermark == "2026-08-01T00:00:00Z"


async def test_reconciliation_distinguishes_receipt_from_observed_state() -> None:
    release, target = await _fixture()
    expected = MutationEffect(
        kind=MutationEffectKind.EXPECTED_PROPERTY,
        target_id=target.id,
        property_name="replicas",
        value=3,
    )
    command = MutationEffect(
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target.id,
        command_ref="provider.scale",
    )
    plan = build_mutation_plan(
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale"),
        targets=(target,),
        effects=(command,),
        rollback_effects=(command,),
        expected_effects=(expected,),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        max_affected_objects=1,
    )
    mismatch = reconcile_expected_effects(
        plan=plan,
        observed={target.id: target},
        observed_at=datetime(2026, 8, 1, 0, 1, tzinfo=UTC),
        evidence_refs=("inventory:1",),
    )
    converged = reconcile_expected_effects(
        plan=plan,
        observed={target.id: replace(target, properties={"id": target.id, "replicas": 3})},
        observed_at=datetime(2026, 8, 1, 0, 2, tzinfo=UTC),
        evidence_refs=("inventory:2",),
    )

    assert mismatch.status is ReconciliationStatus.MISMATCHED
    assert converged.status is ReconciliationStatus.MATCHED
