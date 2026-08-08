"""ActionType V2 semantic contract and proposal compiler tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fdai.core.ontology_platform import (
    MutationEffect,
    MutationEffectKind,
    compile_action_mutation_plan,
)
from fdai.shared.contracts.models import (
    ActionEffectSpec,
    ActionLockScope,
    ActionParameterDeclaration,
    ActionParameterRedaction,
    ActionPostconditionKind,
    ActionPostconditionSpec,
    ActionReadSetReference,
    ActionSemanticContract,
    ActionSemanticEffectKind,
    ActionSubmissionCriterion,
    ActionTargetCardinality,
    ActionTargetSelector,
    ActionTransactionMode,
    ActionTransactionPolicy,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    Operation,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    RollbackKind,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord


def _function(name: str, kind: OntologyFunctionKind) -> OntologyFunctionType:
    return OntologyFunctionType(
        name=name,
        version="1.0.0",
        kind=kind,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def _ref(
    declarations: tuple[OntologyDeclarationRef, ...],
    kind: OntologyDeclarationKind,
    name: str,
) -> OntologyDeclarationRef:
    return next(item for item in declarations if item.kind is kind and item.name == name)


def _fixture(
    *,
    target_cardinality: ActionTargetCardinality = ActionTargetCardinality.ONE,
    max_affected_objects: int = 1,
    planner_kind: OntologyFunctionKind = OntologyFunctionKind.PLAN,
):
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
    functions = (
        _function("query.workloads", OntologyFunctionKind.QUERY),
        _function("validate.capacity", OntologyFunctionKind.VALIDATE),
        _function("plan.scale", planner_kind),
    )
    declarations = build_ontology_release(
        object_types=(object_type,), function_types=functions
    ).declarations
    semantic = ActionSemanticContract(
        target=ActionTargetSelector(
            type_ref=_ref(declarations, OntologyDeclarationKind.OBJECT, object_type.name),
            cardinality=target_cardinality,
        ),
        parameters=(
            ActionParameterDeclaration(
                name="replicas",
                required=True,
                inline_schema={"type": "integer", "minimum": 1, "maximum": 100},
                redaction=ActionParameterRedaction.AUDIT_SAFE,
            ),
        ),
        read_sets=(
            ActionReadSetReference(
                function_ref=_ref(
                    declarations,
                    OntologyDeclarationKind.FUNCTION,
                    "query.workloads",
                ),
                properties=("replicas",),
                max_objects=max_affected_objects,
            ),
        ),
        submission_criteria=(
            ActionSubmissionCriterion(
                function_ref=_ref(
                    declarations,
                    OntologyDeclarationKind.FUNCTION,
                    "validate.capacity",
                )
            ),
        ),
        planner_ref=_ref(
            declarations,
            OntologyDeclarationKind.FUNCTION,
            "plan.scale",
        ),
        effects=(
            ActionEffectSpec(
                effect_id="scale-command",
                kind=ActionSemanticEffectKind.PROVIDER_COMMAND,
                operation_ref="provider.scale",
            ),
        ),
        postconditions=(
            ActionPostconditionSpec(
                postcondition_id="replicas-converged",
                kind=ActionPostconditionKind.PROPERTY,
                observation_ref="property.replicas",
            ),
        ),
        transaction_policy=ActionTransactionPolicy(
            mode=ActionTransactionMode.SAGA,
            lock_scope=ActionLockScope.TARGET_SET,
            max_affected_objects=max_affected_objects,
        ),
    )
    action_type = OntologyActionType(
        schema_version="2.0.0",
        name="ops.scale",
        version="2.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=1.0,
            max_policy_escapes=0,
        ),
        semantic=semantic,
    )
    release = build_ontology_release(
        object_types=(object_type,),
        action_types=(action_type,),
        function_types=functions,
    )
    return object_type, functions, action_type, release


def _target(identifier: str, object_type: OntologyObjectType, release) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=identifier,
        object_type=object_type.name,
        properties={"id": identifier, "replicas": 2},
        revision=1,
        type_ref=release.type_ref(OntologyDeclarationKind.OBJECT, object_type.name),
    )


def _effects(target_id: str):
    command = MutationEffect(
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target_id,
        command_ref="provider.scale",
    )
    expected = MutationEffect(
        kind=MutationEffectKind.EXPECTED_PROPERTY,
        target_id=target_id,
        property_name="replicas",
        value=3,
    )
    return command, expected


def test_legacy_action_type_decodes_without_semantic_contract() -> None:
    action_type = OntologyActionType.model_validate(
        {
            "schema_version": "1.0.0",
            "name": "ops.legacy",
            "version": "1.0.0",
            "operation": "restart",
            "rollback_contract": "state_forward_only",
            "promotion_gate": {
                "min_shadow_days": 1,
                "min_samples": 1,
                "min_accuracy": 1.0,
                "max_policy_escapes": 0,
            },
        }
    )

    assert action_type.semantic is None


def test_compiler_produces_proposal_only_exact_plan_and_validates_existing() -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, expected = _effects(target.id)

    plan = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=functions,
        targets=(target,),
        effects=(command,),
        rollback_effects=(command,),
        expected_effects=(expected,),
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
    )
    validated = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=functions,
        targets=(target,),
        existing_plan=plan,
    )

    assert validated is plan
    assert plan.action_type_ref == release.type_ref(
        OntologyDeclarationKind.ACTION, action_type.name
    )
    assert action_type.semantic is not None
    assert action_type.semantic.planner_ref.declaration_digest in plan.planner_ref
    assert not hasattr(plan, "execution_authority")


def test_compiler_rejects_stale_declaration_ref() -> None:
    object_type, functions, action_type, release = _fixture()
    assert action_type.semantic is not None
    stale_planner = action_type.semantic.planner_ref.model_copy(
        update={"declaration_digest": "sha256:" + "f" * 64}
    )
    stale_action = action_type.model_copy(
        update={"semantic": action_type.semantic.model_copy(update={"planner_ref": stale_planner})}
    )
    stale_release = build_ontology_release(
        object_types=(object_type,),
        action_types=(stale_action,),
        function_types=functions,
    )
    target = _target("workload-a", object_type, stale_release)
    command, expected = _effects(target.id)

    with pytest.raises(ValueError, match="stale or absent"):
        compile_action_mutation_plan(
            action_type=stale_action,
            release=stale_release,
            function_types=functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(command,),
            expected_effects=(expected,),
            created_at=datetime(2026, 8, 8, tzinfo=UTC),
        )


def test_compiler_preserves_mutation_plan_rollback_coverage() -> None:
    object_type, functions, action_type, release = _fixture(
        target_cardinality=ActionTargetCardinality.SET,
        max_affected_objects=2,
    )
    targets = (
        _target("workload-a", object_type, release),
        _target("workload-b", object_type, release),
    )
    first_command, expected = _effects(targets[0].id)
    second_command = first_command.model_copy(update={"target_id": targets[1].id})

    with pytest.raises(ValueError, match="rollback effects MUST cover"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=targets,
            effects=(first_command, second_command),
            rollback_effects=(first_command,),
            expected_effects=(expected,),
            created_at=datetime(2026, 8, 8, tzinfo=UTC),
        )


def test_compiler_enforces_max_target_bound() -> None:
    object_type, functions, action_type, release = _fixture(
        target_cardinality=ActionTargetCardinality.SET,
        max_affected_objects=1,
    )
    targets = (
        _target("workload-a", object_type, release),
        _target("workload-b", object_type, release),
    )
    command, expected = _effects(targets[0].id)

    with pytest.raises(ValueError, match="transaction bound"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=targets,
            effects=(command,),
            rollback_effects=(command,),
            expected_effects=(expected,),
            created_at=datetime(2026, 8, 8, tzinfo=UTC),
        )


def test_compiler_requires_plan_function_kind() -> None:
    object_type, functions, action_type, release = _fixture(
        planner_kind=OntologyFunctionKind.DERIVE
    )
    target = _target("workload-a", object_type, release)
    command, expected = _effects(target.id)

    with pytest.raises(ValueError, match="planner FunctionType MUST have kind plan"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(command,),
            expected_effects=(expected,),
            created_at=datetime(2026, 8, 8, tzinfo=UTC),
        )


def test_compiler_rejects_function_content_outside_active_release() -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, expected = _effects(target.id)
    mismatched_functions = (
        *functions[:-1],
        functions[-1].model_copy(update={"kind": OntologyFunctionKind.DERIVE}),
    )

    with pytest.raises(ValueError, match="does not match the active ontology release"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=mismatched_functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(command,),
            expected_effects=(expected,),
            created_at=datetime(2026, 8, 8, tzinfo=UTC),
        )


def test_semantic_effects_and_postconditions_cannot_grant_authority() -> None:
    with pytest.raises(ValidationError, match="grants_authority"):
        ActionEffectSpec(
            effect_id="unsafe",
            kind=ActionSemanticEffectKind.PROVIDER_COMMAND,
            operation_ref="provider.scale",
            grants_authority=True,
        )
    with pytest.raises(ValidationError, match="grants_authority"):
        ActionPostconditionSpec(
            postcondition_id="unsafe",
            kind=ActionPostconditionKind.PROPERTY,
            observation_ref="property.replicas",
            grants_authority=True,
        )


def test_inline_parameter_schema_cannot_hide_declaration_ref() -> None:
    with pytest.raises(ValidationError, match="uses schema_ref"):
        ActionParameterDeclaration(
            name="target",
            inline_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"target": {"$ref": "#/$defs/Workload"}},
            },
            redaction=ActionParameterRedaction.AUDIT_SAFE,
        )
