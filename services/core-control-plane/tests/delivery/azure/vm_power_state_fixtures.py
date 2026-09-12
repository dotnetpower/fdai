"""Synthetic semantic fixtures for VM power-state observation tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.ontology_platform.action_plans import compile_action_mutation_plan
from fdai.core.ontology_platform.kinetics import (
    MutationEffect,
    MutationEffectKind,
)
from fdai.core.ontology_platform.reconciliation_binding import (
    ResolvedReconciliationArtifacts,
)
from fdai.shared.contracts.models import (
    Action,
    ActionEffectSpec,
    ActionLockScope,
    ActionPostconditionKind,
    ActionPostconditionSpec,
    ActionSemanticContract,
    ActionSemanticEffectKind,
    ActionTargetCardinality,
    ActionTargetSelector,
    ActionTransactionMode,
    ActionTransactionPolicy,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    Operation,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    RollbackKind,
    RollbackRef,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

CREATED_AT = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)
RESOURCE_REF = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/rg-example/providers/Microsoft.Compute/virtualMachines/vm-example"
)


def vm_start_fixture() -> tuple[ResolvedReconciliationArtifacts, Action]:
    """Return one synthetic semantic plan for ``ops.start-vm@1.0.0``."""

    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="VirtualMachine",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "power_state": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )
    planner = OntologyFunctionType(
        name="plan.vm-start",
        version="1.0.0",
        kind=OntologyFunctionKind.PLAN,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    declarations = build_ontology_release(
        object_types=(object_type,),
        function_types=(planner,),
    ).declarations
    object_ref = next(
        item
        for item in declarations
        if item.kind is OntologyDeclarationKind.OBJECT and item.name == object_type.name
    )
    planner_ref = next(
        item
        for item in declarations
        if item.kind is OntologyDeclarationKind.FUNCTION and item.name == planner.name
    )
    action_type = OntologyActionType(
        schema_version="2.0.0",
        name="ops.start-vm",
        version="1.0.0",
        operation=Operation.ENABLE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=30,
            min_accuracy=0.98,
            max_policy_escapes=0,
        ),
        semantic=ActionSemanticContract(
            target=ActionTargetSelector(
                type_ref=object_ref,
                cardinality=ActionTargetCardinality.ONE,
            ),
            planner_ref=planner_ref,
            effects=(
                ActionEffectSpec(
                    effect_id="vm-start-command",
                    kind=ActionSemanticEffectKind.PROVIDER_COMMAND,
                    operation_ref="azure.compute.vm.start",
                    rollback_operation_ref="azure.compute.vm.deallocate",
                ),
            ),
            postconditions=(
                ActionPostconditionSpec(
                    postcondition_id="vm-running",
                    kind=ActionPostconditionKind.PROPERTY,
                    observation_ref="property.power_state",
                ),
            ),
            transaction_policy=ActionTransactionPolicy(
                mode=ActionTransactionMode.SAGA,
                lock_scope=ActionLockScope.TARGET,
                max_affected_objects=1,
            ),
        ),
    )
    release = build_ontology_release(
        object_types=(object_type,),
        action_types=(action_type,),
        function_types=(planner,),
    )
    target = OntologyObjectRecord(
        id=RESOURCE_REF,
        object_type="VirtualMachine",
        properties={"id": RESOURCE_REF, "power_state": "deallocated"},
        revision=3,
        type_ref=release.type_ref(
            OntologyDeclarationKind.OBJECT,
            "VirtualMachine",
        ),
    )
    command = MutationEffect(
        effect_id="vm-start-command",
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target.id,
        command_ref="azure.compute.vm.start",
    )
    rollback = command.model_copy(update={"command_ref": "azure.compute.vm.deallocate"})
    expected = MutationEffect(
        effect_id="vm-running",
        kind=MutationEffectKind.EXPECTED_PROPERTY,
        target_id=target.id,
        property_name="power_state",
        value="running",
        observation_ref="property.power_state",
    )
    plan = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=(planner,),
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=(expected,),
        created_at=CREATED_AT,
        arguments={},
    )
    action = Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000010",
        idempotency_key="vm-start-example",
        event_id="00000000-0000-0000-0000-000000000001",
        action_type=action_type.name,
        action_type_ref=plan.action_type_ref,
        target_resource_ref=target.id,
        operation=action_type.operation,
        params={},
        stop_condition="provider_api_error_streak",
        stop_conditions=[{"kind": "provider_api_error_streak", "count": 3}],
        rollback_ref=RollbackRef(kind=RollbackKind.STATE_FORWARD_ONLY),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.ENFORCE,
        citing_rules=["example.vm.start"],
        created_at=CREATED_AT,
        executor_identity_ref="identity:thor:resilience",
    )
    return ResolvedReconciliationArtifacts(plan, action_type, release), action


__all__ = ["CREATED_AT", "RESOURCE_REF", "vm_start_fixture"]
