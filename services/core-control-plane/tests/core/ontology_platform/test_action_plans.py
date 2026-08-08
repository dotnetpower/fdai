"""ActionType V2 semantic contract and proposal compiler tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform import (
    ActionReadSetReceipt,
    CriterionResult,
    MutationEffect,
    MutationEffectKind,
    MutationPlan,
    build_mutation_plan,
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
from pydantic import ValidationError


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
            ActionParameterDeclaration(
                name="credential",
                inline_schema={"type": "string", "minLength": 8},
                redaction=ActionParameterRedaction.REDACT,
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
                rollback_operation_ref="provider.scale.rollback",
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
        effect_id="scale-command",
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target_id,
        command_ref="provider.scale",
    )
    rollback = MutationEffect(
        effect_id="scale-command",
        kind=MutationEffectKind.PROVIDER_COMMAND,
        target_id=target_id,
        command_ref="provider.scale.rollback",
    )
    expected = MutationEffect(
        effect_id="replicas-converged",
        kind=MutationEffectKind.EXPECTED_PROPERTY,
        target_id=target_id,
        property_name="replicas",
        value=3,
        observation_ref="property.replicas",
    )
    return command, rollback, expected


def _compile_evidence(
    action_type: OntologyActionType,
    created_at: datetime,
) -> dict[str, object]:
    assert action_type.semantic is not None
    read_set = action_type.semantic.read_sets[0]
    criterion = action_type.semantic.submission_criteria[0]
    return {
        "arguments": {"replicas": 3},
        "read_set_receipts": (
            ActionReadSetReceipt.create(
                function_ref=read_set.function_ref,
                properties=read_set.properties,
                object_count=1,
                complete=True,
                truncated=False,
                observed_at=created_at - timedelta(seconds=5),
                fresh_until=created_at + timedelta(minutes=1),
                evidence_refs=("evidence:read-set",),
            ),
        ),
        "criterion_results": (
            CriterionResult.create(
                criterion_ref=criterion.criterion_ref,
                function_ref=criterion.function_ref,
                passed=True,
                reason_code="capacity_ready",
                evidence_refs=("evidence:criterion",),
                complete=True,
                truncated=False,
                observed_at=created_at - timedelta(seconds=5),
                fresh_until=created_at + timedelta(minutes=1),
            ),
        ),
    }


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
    command, rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    plan = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=functions,
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=(expected,),
        created_at=created_at,
        **_compile_evidence(action_type, created_at),
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
    assert plan.schema_version == "2.0.0"
    assert plan.transaction_mode is ActionTransactionMode.SAGA
    assert plan.lock_scope is ActionLockScope.TARGET_SET
    assert plan.lock_keys == ("ontology-target:workload-a",)
    assert plan.max_affected_objects == 1
    assert plan.arguments_digest is not None
    assert plan.argument_bindings[0].name == "replicas"
    assert plan.read_set_receipt_digests
    assert plan.criterion_receipt_digests
    assert not hasattr(plan, "execution_authority")


def test_compiler_rejects_effect_without_declared_effect_id_binding() -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    unbound_command = command.model_copy(update={"effect_id": None})
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match="effect_id"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=(target,),
            effects=(unbound_command,),
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **_compile_evidence(action_type, created_at),
        )


@pytest.mark.parametrize(
    ("effect_change", "message"),
    [
        ("missing", "missing declared effects"),
        ("duplicate", "duplicate forward effects"),
        ("undeclared", "undeclared effects"),
        ("operation", "does not match operation_ref"),
    ],
)
def test_compiler_rejects_non_exact_forward_effect_set(
    effect_change: str,
    message: str,
) -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    effects: tuple[MutationEffect, ...]
    if effect_change == "missing":
        effects = ()
    elif effect_change == "duplicate":
        effects = (command, command)
    elif effect_change == "undeclared":
        effects = (command.model_copy(update={"effect_id": "not-declared"}),)
    else:
        effects = (command.model_copy(update={"command_ref": "provider.other"}),)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match=message):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=(target,),
            effects=effects,
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **_compile_evidence(action_type, created_at),
        )


def test_provider_command_effect_requires_command_ref() -> None:
    with pytest.raises(ValidationError, match="requires command_ref"):
        MutationEffect(
            effect_id="scale-command",
            kind=MutationEffectKind.PROVIDER_COMMAND,
            target_id="workload-a",
        )


@pytest.mark.parametrize(
    ("expected_change", "message"),
    [
        ("missing", "missing declared effects"),
        ("duplicate", "duplicate expected effects"),
        ("undeclared", "undeclared effects"),
        ("property", "property_name does not match"),
        ("observation", "observation_ref does not match"),
    ],
)
def test_compiler_rejects_non_exact_postcondition_effect_set(
    expected_change: str,
    message: str,
) -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    expected_effects: tuple[MutationEffect, ...]
    if expected_change == "missing":
        expected_effects = ()
    elif expected_change == "duplicate":
        expected_effects = (expected, expected)
    elif expected_change == "undeclared":
        expected_effects = (expected.model_copy(update={"effect_id": "not-declared"}),)
    elif expected_change == "property":
        expected_effects = (expected.model_copy(update={"property_name": "other"}),)
    else:
        expected_effects = (expected.model_copy(update={"observation_ref": "property.other"}),)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match=message):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(rollback,),
            expected_effects=expected_effects,
            created_at=created_at,
            **_compile_evidence(action_type, created_at),
        )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "missing required parameters"),
        ({"replicas": 3, "extra": True}, "undeclared parameters"),
        ({"replicas": 0}, "violates inline_schema"),
        ({"replicas": 3.5}, "violates inline_schema"),
    ],
)
def test_compiler_validates_canonical_action_arguments(
    arguments: dict[str, object],
    message: str,
) -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)
    evidence = _compile_evidence(action_type, created_at)
    evidence["arguments"] = arguments

    with pytest.raises(ValueError, match=message):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **evidence,
        )


def test_compiler_binds_arguments_without_retaining_redacted_value() -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)
    evidence = _compile_evidence(action_type, created_at)
    evidence["arguments"] = {"replicas": 3, "credential": "secret-value"}

    plan = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=functions,
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=(expected,),
        created_at=created_at,
        **evidence,
    )
    serialized = plan.model_dump_json()
    binding = next(item for item in plan.argument_bindings if item.name == "credential")

    assert "secret-value" not in serialized
    assert binding.redacted is True
    assert binding.safe_value_json == '"<redacted>"'
    replay_evidence = _compile_evidence(action_type, created_at)
    replay_evidence["arguments"] = {"replicas": 4, "credential": "secret-value"}
    replay = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=functions,
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=(expected,),
        created_at=created_at,
        **replay_evidence,
    )
    assert replay.digest != plan.digest


@pytest.mark.parametrize(
    ("receipt_kind", "change", "message"),
    [
        ("read", "missing", "read-set receipts are missing"),
        ("read", "tampered", "digest does not match"),
        ("read", "incomplete", "MUST be complete"),
        ("read", "truncated", "MUST be untruncated"),
        ("read", "stale", "is stale"),
        ("criterion", "missing", "CriterionResult receipts are missing"),
        ("criterion", "tampered", "digest does not match"),
        ("criterion", "incomplete", "MUST be complete"),
        ("criterion", "truncated", "MUST be untruncated"),
        ("criterion", "stale", "is stale"),
    ],
)
def test_compiler_requires_complete_fresh_content_addressed_receipts(
    receipt_kind: str,
    change: str,
    message: str,
) -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)
    evidence = _compile_evidence(action_type, created_at)
    key = "read_set_receipts" if receipt_kind == "read" else "criterion_results"
    receipt = evidence[key][0]  # type: ignore[index]
    if change == "missing":
        evidence[key] = ()
    elif change == "tampered":
        evidence[key] = (receipt.model_copy(update={"complete": False}),)
    elif change == "incomplete":
        evidence[key] = (receipt.model_copy(update={"complete": False}),)
        evidence[key] = (
            type(receipt).create(
                **receipt.model_dump(exclude={"receipt_digest", "complete"}),
                complete=False,
            ),
        )
    elif change == "truncated":
        evidence[key] = (
            type(receipt).create(
                **receipt.model_dump(exclude={"receipt_digest", "truncated"}),
                truncated=True,
            ),
        )
    else:
        evidence[key] = (
            type(receipt).create(
                **receipt.model_dump(exclude={"receipt_digest", "fresh_until"}),
                fresh_until=created_at - timedelta(seconds=1),
            ),
        )

    with pytest.raises((ValueError, ValidationError), match=message):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **evidence,
        )


def test_set_cardinality_requires_target_set_lock_scope() -> None:
    object_type, functions, action_type, _release = _fixture(
        target_cardinality=ActionTargetCardinality.SET,
        max_affected_objects=2,
    )
    assert action_type.semantic is not None
    invalid_policy = action_type.semantic.transaction_policy.model_copy(
        update={"lock_scope": ActionLockScope.TARGET}
    )

    with pytest.raises(ValidationError, match="target_set lock scope"):
        ActionSemanticContract.model_validate(
            action_type.semantic.model_dump() | {"transaction_policy": invalid_policy.model_dump()}
        )


def test_compiler_binds_sorted_target_set_locks_and_effect_cardinality() -> None:
    object_type, functions, action_type, release = _fixture(
        target_cardinality=ActionTargetCardinality.SET,
        max_affected_objects=2,
    )
    targets = (
        _target("workload-b", object_type, release),
        _target("workload-a", object_type, release),
    )
    first = _effects(targets[0].id)
    second = _effects(targets[1].id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    plan = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=functions,
        targets=targets,
        effects=(first[0], second[0]),
        rollback_effects=(first[1], second[1]),
        expected_effects=(first[2], second[2]),
        created_at=created_at,
        **_compile_evidence(action_type, created_at),
    )

    assert plan.lock_scope is ActionLockScope.TARGET_SET
    assert plan.lock_keys == (
        "ontology-target:workload-a",
        "ontology-target:workload-b",
    )
    assert plan.max_affected_objects == 2


def test_v2_mutation_plan_decode_rejects_lock_keys_for_other_targets() -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)
    plan = compile_action_mutation_plan(
        action_type=action_type,
        release=release,
        function_types=functions,
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=(expected,),
        created_at=created_at,
        **_compile_evidence(action_type, created_at),
    )
    payload = plan.model_dump(mode="json")
    payload["lock_keys"] = ["ontology-target:workload-b"]

    with pytest.raises(ValidationError, match="lock_keys MUST match"):
        MutationPlan.model_validate(payload)


def test_irreversible_action_binds_flag_without_fake_rollback() -> None:
    object_type, functions, reversible, _release = _fixture()
    assert reversible.semantic is not None
    effect = reversible.semantic.effects[0].model_copy(update={"rollback_operation_ref": None})
    irreversible = OntologyActionType.model_validate(
        reversible.model_dump()
        | {
            "irreversible": True,
            "semantic": reversible.semantic.model_copy(update={"effects": (effect,)}).model_dump(),
        }
    )
    release = build_ontology_release(
        object_types=(object_type,),
        action_types=(irreversible,),
        function_types=functions,
    )
    target = _target("workload-a", object_type, release)
    command, _rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    plan = compile_action_mutation_plan(
        action_type=irreversible,
        release=release,
        function_types=functions,
        targets=(target,),
        effects=(command,),
        rollback_effects=(),
        expected_effects=(expected,),
        created_at=created_at,
        **_compile_evidence(irreversible, created_at),
    )

    assert plan.irreversible is True
    assert plan.rollback_effects == ()


def test_legacy_mutation_plan_payload_decodes_without_v2_identity_fields() -> None:
    object_type, _functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    legacy = build_mutation_plan(
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, action_type.name),
        planner_ref="legacy-planner",
        targets=(target,),
        effects=(command,),
        rollback_effects=(rollback,),
        expected_effects=(expected,),
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
        max_affected_objects=1,
    )
    payload = legacy.model_dump(mode="json", exclude_defaults=True, exclude_none=True)

    decoded = MutationPlan.model_validate(payload)

    assert decoded.schema_version == "1.0.0"
    assert decoded.arguments_digest is None
    assert decoded.lock_keys == ()


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
    command, rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match="stale or absent"):
        compile_action_mutation_plan(
            action_type=stale_action,
            release=stale_release,
            function_types=functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **_compile_evidence(stale_action, created_at),
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
    first_command, first_rollback, expected = _effects(targets[0].id)
    second_command = first_command.model_copy(update={"target_id": targets[1].id})
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match="rollback effects MUST cover"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=targets,
            effects=(first_command, second_command),
            rollback_effects=(first_rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **_compile_evidence(action_type, created_at),
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
    command, rollback, expected = _effects(targets[0].id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match="transaction bound"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=targets,
            effects=(command,),
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **_compile_evidence(action_type, created_at),
        )


def test_compiler_requires_plan_function_kind() -> None:
    object_type, functions, action_type, release = _fixture(
        planner_kind=OntologyFunctionKind.DERIVE
    )
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match="planner FunctionType MUST have kind plan"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **_compile_evidence(action_type, created_at),
        )


def test_compiler_rejects_function_content_outside_active_release() -> None:
    object_type, functions, action_type, release = _fixture()
    target = _target("workload-a", object_type, release)
    command, rollback, expected = _effects(target.id)
    mismatched_functions = (
        *functions[:-1],
        functions[-1].model_copy(update={"kind": OntologyFunctionKind.DERIVE}),
    )
    created_at = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ValueError, match="does not match the active ontology release"):
        compile_action_mutation_plan(
            action_type=action_type,
            release=release,
            function_types=mismatched_functions,
            targets=(target,),
            effects=(command,),
            rollback_effects=(rollback,),
            expected_effects=(expected,),
            created_at=created_at,
            **_compile_evidence(action_type, created_at),
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
