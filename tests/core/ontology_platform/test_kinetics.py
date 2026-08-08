"""Kinetic ontology safety tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.ontology_platform import (
    AuthorityClass,
    CriterionResult,
    FunctionInvocationContext,
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
    CeilingRole,
    LogicCapability,
    LogicExecutionClass,
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
        planner_ref="plan.scale@1.0.0",
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
    declaration = OntologyFunctionType(
        name="query.workloads",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    validate_decl = declaration.model_copy(
        update={"name": "validate.workload", "kind": OntologyFunctionKind.VALIDATE}
    )
    release = build_ontology_release(function_types=(declaration, validate_decl))
    registry = OntologyFunctionRegistry(release=release)

    async def query(_arguments):
        return {"count": 1}

    registry.register(declaration, query)
    assert await registry.invoke("query.workloads", {}) == {"count": 1}

    async def validate(_arguments):
        function_ref = next(
            item
            for item in release.declarations
            if item.kind is OntologyDeclarationKind.FUNCTION and item.name == validate_decl.name
        )
        observed_at = datetime(2026, 8, 1, tzinfo=UTC)
        return CriterionResult.create(
            function_ref=function_ref,
            passed=True,
            reason_code="ready",
            evidence_refs=("object:x",),
            complete=True,
            truncated=False,
            observed_at=observed_at,
            fresh_until=observed_at,
        )

    registry.register(validate_decl, validate)
    result = await registry.invoke("validate.workload", {})
    assert isinstance(result, CriterionResult)


async def test_function_invocation_is_authorized_release_pinned_and_replay_stable() -> None:
    declaration = OntologyFunctionType(
        name="simulate.capacity",
        version="1.0.0",
        kind=OntologyFunctionKind.DERIVE,
        capabilities=[LogicCapability.SIMULATE],
        artifact_digest="sha256:" + "c" * 64,
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["replicas", "fdai_seed"],
            "properties": {
                "replicas": {"type": "integer"},
                "fdai_seed": {"type": "integer"},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["predicted"],
            "properties": {"predicted": {"type": "number"}},
        },
        execution_class=LogicExecutionClass.SEEDED_STOCHASTIC,
        seed_field="fdai_seed",
        required_role=CeilingRole.CONTRIBUTOR,
        purpose_bindings=["operational_planning"],
        allowed_agents=["Freyr"],
    )
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)

    async def simulate(arguments):
        return {"predicted": arguments["replicas"] + arguments["fdai_seed"] % 2}

    registry.register(declaration, simulate)
    context = FunctionInvocationContext(
        caller_agent="Freyr",
        caller_role=CeilingRole.CONTRIBUTOR,
        purposes=("operational_planning",),
        evidence_refs=("snapshot:1",),
    )
    first, first_receipt = await registry.invoke_with_receipt(
        declaration.name, {"replicas": 2}, context=context
    )
    replay, replay_receipt = await registry.invoke_with_receipt(
        declaration.name, {"replicas": 2}, context=context
    )

    assert replay == first
    assert replay_receipt.request_id == first_receipt.request_id
    assert replay_receipt.invocation_id == first_receipt.invocation_id
    assert replay_receipt.seed == first_receipt.seed
    assert replay_receipt.function_ref.catalog_digest == release.digest
    assert registry.release_ref == release.ref()
    with pytest.raises(PermissionError, match="role"):
        await registry.invoke(
            declaration.name,
            {"replicas": 2},
            context=context.model_copy(update={"caller_role": CeilingRole.READER}),
        )
    with pytest.raises(ValueError, match="seed field .* runtime-owned"):
        await registry.invoke(
            declaration.name,
            {"replicas": 2, "fdai_seed": 7},
            context=context,
        )


async def test_function_registry_rejects_same_version_substitution_and_retains_copy() -> None:
    declaration = OntologyFunctionType(
        name="query.workloads",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    release = build_ontology_release(function_types=(declaration,))
    substituted = declaration.model_copy(update={"artifact_digest": "sha256:" + "b" * 64})

    async def query(_arguments):
        return {"count": 1}

    with pytest.raises(ValueError, match="does not match release"):
        OntologyFunctionRegistry(release=release).register(substituted, query)

    registry = OntologyFunctionRegistry(release=release)
    registry.register(declaration, query)
    declaration.input_schema["type"] = "array"
    returned = registry.declaration(declaration.name)
    returned.input_schema["type"] = "string"

    assert registry.declaration(declaration.name).input_schema == {"type": "object"}


async def test_function_registry_requires_isolation_for_network_or_credentials() -> None:
    declaration = OntologyFunctionType(
        name="query.remote",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        network_allowed=True,
        credentials_allowed=True,
    )
    registry = OntologyFunctionRegistry(
        release=build_ontology_release(function_types=(declaration,))
    )

    async def query(_arguments):
        return {}

    with pytest.raises(ValueError, match="isolated runner"):
        registry.register(declaration, query)


async def test_function_registry_enforces_wall_timeout_and_canonical_output_bytes() -> None:
    timeout_declaration = OntologyFunctionType(
        name="query.slow",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        timeout_seconds=1,
    )
    output_declaration = timeout_declaration.model_copy(
        update={
            "name": "query.large",
            "artifact_digest": "sha256:" + "b" * 64,
            "max_output_bytes": 16,
        }
    )
    registry = OntologyFunctionRegistry(
        release=build_ontology_release(function_types=(timeout_declaration, output_declaration))
    )

    async def slow(_arguments):
        await asyncio.sleep(60)
        return {}

    async def large(_arguments):
        return {"value": "x" * 64}

    registry.register(timeout_declaration, slow)
    registry.register(output_declaration, large)

    with pytest.raises(TimeoutError, match="wall timeout"):
        await registry.invoke(timeout_declaration.name, {})
    with pytest.raises(ValueError, match="max_output_bytes"):
        await registry.invoke(output_declaration.name, {})


def test_function_invocation_context_deduplicates_and_bounds_metadata() -> None:
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        purposes=("operations-review", "operations-review"),
        evidence_refs=("evidence:1", "evidence:1"),
    )

    assert context.purposes == ("operations-review",)
    assert context.evidence_refs == ("evidence:1",)
    with pytest.raises(ValueError, match="purposes exceeds 16"):
        FunctionInvocationContext(
            caller_agent="Bragi",
            purposes=tuple(f"purpose-{index}" for index in range(17)),
        )
    with pytest.raises(ValueError, match="evidence_refs exceeds 64"):
        FunctionInvocationContext(
            caller_agent="Bragi",
            evidence_refs=tuple(f"evidence:{index}" for index in range(65)),
        )


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

    batch = project_source_records(
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

    assert batch.objects[0].type_ref == binding.object_type_ref
    assert batch.objects[0].properties == {"id": "workload-a", "replicas": 2}
    assert batch.watermark == "2026-08-01T00:00:00Z"


async def test_projection_rejects_duplicate_identity_and_emits_tombstone() -> None:
    release, _target = await _fixture()
    binding = ProjectionBinding(
        binding_id="inventory.workload",
        source_id="inventory",
        object_type_ref=release.type_ref(OntologyDeclarationKind.OBJECT, "Workload"),
        authority_class=AuthorityClass.PROVIDER_OBSERVED,
        identity_field="resource_id",
        property_map={"resource_id": "id", "replica_count": "replicas"},
        watermark_field="observed_at",
        delete_field="deleted",
    )
    duplicate = {
        "resource_id": "workload-a",
        "replica_count": 2,
        "observed_at": "2026-08-01T00:00:00Z",
    }
    with pytest.raises(ValueError, match="duplicate identity"):
        project_source_records(binding=binding, records=(duplicate, duplicate), release=release)

    batch = project_source_records(
        binding=binding,
        records=({**duplicate, "deleted": True},),
        release=release,
    )
    assert batch.objects == ()
    assert batch.deleted_ids == ("workload-a",)

    with pytest.raises(ValueError, match="delete marker MUST be boolean"):
        project_source_records(
            binding=binding,
            records=({**duplicate, "deleted": "true"},),
            release=release,
        )


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
        planner_ref="plan.scale@1.0.0",
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
        deadline=datetime(2026, 8, 1, 0, 5, tzinfo=UTC),
        evidence_refs=("inventory:1",),
    )
    converged = reconcile_expected_effects(
        plan=plan,
        observed={target.id: replace(target, properties={"id": target.id, "replicas": 3})},
        observed_at=datetime(2026, 8, 1, 0, 2, tzinfo=UTC),
        deadline=datetime(2026, 8, 1, 0, 5, tzinfo=UTC),
        evidence_refs=("inventory:2",),
    )

    assert mismatch.status is ReconciliationStatus.MISMATCHED
    assert converged.status is ReconciliationStatus.MATCHED

    timed_out = reconcile_expected_effects(
        plan=plan,
        observed={},
        observed_at=datetime(2026, 8, 1, 0, 6, tzinfo=UTC),
        deadline=datetime(2026, 8, 1, 0, 5, tzinfo=UTC),
        evidence_refs=("inventory:timeout",),
    )
    assert timed_out.status is ReconciliationStatus.TIMED_OUT


async def test_mutation_plan_requires_rollback_coverage() -> None:
    release, target = await _fixture()
    with pytest.raises(ValueError, match="rollback effects MUST cover"):
        build_mutation_plan(
            action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale"),
            planner_ref="plan.scale@1.0.0",
            targets=(target,),
            effects=(
                MutationEffect(
                    kind=MutationEffectKind.PROVIDER_COMMAND,
                    target_id=target.id,
                    command_ref="provider.scale",
                ),
            ),
            rollback_effects=(
                MutationEffect(
                    kind=MutationEffectKind.NOTIFICATION,
                    target_id="another-target",
                ),
            ),
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            max_affected_objects=1,
        )
