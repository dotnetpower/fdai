"""Pure ActionType semantic compilation into proposal-only mutation plans."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator

from fdai.shared.contracts.models import (
    ActionParameterRedaction,
    ActionPostconditionKind,
    ActionTargetCardinality,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .functions import ontology_function_digest
from .interfaces import CompiledInterfaceCatalog
from .kinetics import (
    ActionArgumentBinding,
    ActionReadSetReceipt,
    CriterionResult,
    MutationEffect,
    MutationEffectKind,
    MutationPlan,
)
from .planning import build_mutation_plan, validate_plan_revisions


def compile_action_mutation_plan(
    *,
    action_type: OntologyActionType,
    release: OntologyRelease,
    function_types: Sequence[OntologyFunctionType],
    targets: Sequence[OntologyObjectRecord],
    effects: Sequence[MutationEffect] = (),
    rollback_effects: Sequence[MutationEffect] = (),
    expected_effects: Sequence[MutationEffect] = (),
    arguments: Mapping[str, Any] | None = None,
    read_set_receipts: Sequence[ActionReadSetReceipt] = (),
    criterion_results: Sequence[CriterionResult] = (),
    created_at: datetime | None = None,
    interfaces: CompiledInterfaceCatalog | None = None,
    existing_plan: MutationPlan | None = None,
) -> MutationPlan:
    """Build or verify an immutable proposal without granting execution authority.

    All semantic references must belong to ``release`` exactly. Function subtypes,
    target cardinality, target revisions, declared effects, rollback coverage, and
    an existing plan's digest are checked before the proposal is returned.
    """

    semantic = action_type.semantic
    if semantic is None:
        raise ValueError("ActionType semantic contract is required for semantic compilation")
    action_declaration = build_ontology_release(action_types=(action_type,)).declarations[0]
    if action_declaration not in release.declarations:
        raise ValueError("ActionType declaration does not match the active ontology release")
    action_type_ref = release.type_ref(OntologyDeclarationKind.ACTION, action_type.name)
    if action_type_ref.version != action_type.version:
        raise ValueError("ActionType version does not match the active ontology release")

    functions = _function_index(function_types)
    _validate_semantic_references(action_type, release, functions)
    _validate_targets(action_type, release, targets, interfaces)
    planner_identity = _planner_identity(semantic.planner_ref)

    if existing_plan is not None:
        if (
            effects
            or rollback_effects
            or expected_effects
            or arguments is not None
            or read_set_receipts
            or criterion_results
            or created_at is not None
        ):
            raise ValueError("existing MutationPlan validation does not accept replacement fields")
        _validate_effects(
            action_type,
            targets,
            existing_plan.effects,
            existing_plan.rollback_effects,
            existing_plan.expected_effects,
        )
        validate_plan_revisions(existing_plan, {target.id: target for target in targets})
        candidate = build_mutation_plan(
            action_type_ref=action_type_ref,
            planner_ref=planner_identity,
            targets=targets,
            effects=existing_plan.effects,
            rollback_effects=existing_plan.rollback_effects,
            expected_effects=existing_plan.expected_effects,
            created_at=existing_plan.created_at,
            max_affected_objects=semantic.transaction_policy.max_affected_objects,
            schema_version="2.0.0",
            arguments_digest=existing_plan.arguments_digest,
            argument_bindings=existing_plan.argument_bindings,
            read_set_receipt_digests=existing_plan.read_set_receipt_digests,
            criterion_receipt_digests=existing_plan.criterion_receipt_digests,
            transaction_mode=semantic.transaction_policy.mode,
            lock_scope=semantic.transaction_policy.lock_scope,
            lock_keys=_lock_keys(targets),
            irreversible=action_type.irreversible,
        )
        if candidate != existing_plan:
            raise ValueError("existing MutationPlan does not match the active ActionType contract")
        return existing_plan

    if created_at is None:
        raise ValueError("semantic mutation-plan compilation requires created_at")
    argument_bindings, arguments_digest = _validate_arguments(action_type, arguments or {})
    read_set_receipt_digests = _validate_read_set_receipts(
        action_type,
        read_set_receipts,
        created_at=created_at,
    )
    criterion_receipt_digests = _validate_criterion_results(
        action_type,
        criterion_results,
        created_at=created_at,
    )
    _validate_effects(
        action_type,
        targets,
        effects,
        rollback_effects,
        expected_effects,
    )
    return build_mutation_plan(
        action_type_ref=action_type_ref,
        planner_ref=planner_identity,
        targets=targets,
        effects=effects,
        rollback_effects=rollback_effects,
        expected_effects=expected_effects,
        created_at=created_at,
        max_affected_objects=semantic.transaction_policy.max_affected_objects,
        schema_version="2.0.0",
        arguments_digest=arguments_digest,
        argument_bindings=argument_bindings,
        read_set_receipt_digests=read_set_receipt_digests,
        criterion_receipt_digests=criterion_receipt_digests,
        transaction_mode=semantic.transaction_policy.mode,
        lock_scope=semantic.transaction_policy.lock_scope,
        lock_keys=_lock_keys(targets),
        irreversible=action_type.irreversible,
    )


def _validate_arguments(
    action_type: OntologyActionType,
    arguments: Mapping[str, Any],
) -> tuple[tuple[ActionArgumentBinding, ...], str]:
    semantic = action_type.semantic
    if semantic is None:  # pragma: no cover - checked by public function
        raise RuntimeError("semantic contract is unavailable")
    declarations = {item.name: item for item in semantic.parameters}
    supplied = set(arguments)
    required = {item.name for item in semantic.parameters if item.required}
    missing = sorted(required - supplied)
    if missing:
        raise ValueError(f"action arguments are missing required parameters: {missing}")
    extras = sorted(supplied - set(declarations))
    if extras:
        raise ValueError(f"action arguments contain undeclared parameters: {extras}")

    normalized = dict(arguments)
    arguments_digest = ontology_function_digest(normalized)
    bindings: list[ActionArgumentBinding] = []
    for name in sorted(normalized):
        declaration = declarations[name]
        value = normalized[name]
        if declaration.inline_schema is not None:
            errors = list(Draft202012Validator(declaration.inline_schema).iter_errors(value))
            if errors:
                raise ValueError(f"action argument {name!r} violates inline_schema")
        value_digest = ontology_function_digest(value)
        redacted = declaration.redaction is ActionParameterRedaction.REDACT
        safe_value = "<redacted>" if redacted else value
        bindings.append(
            ActionArgumentBinding(
                name=name,
                value_digest=value_digest,
                redacted=redacted,
                safe_value_json=_canonical_json(safe_value),
            )
        )
    return tuple(bindings), arguments_digest


def _validate_read_set_receipts(
    action_type: OntologyActionType,
    receipts: Sequence[ActionReadSetReceipt],
    *,
    created_at: datetime,
) -> tuple[str, ...]:
    semantic = action_type.semantic
    if semantic is None:  # pragma: no cover - checked by public function
        raise RuntimeError("semantic contract is unavailable")
    declared = {_reference_key(item.function_ref): item for item in semantic.read_sets}
    supplied: dict[tuple[str, str, str], ActionReadSetReceipt] = {}
    for raw_receipt in receipts:
        receipt = ActionReadSetReceipt.model_validate(raw_receipt.model_dump(mode="json"))
        key = _reference_key(receipt.function_ref)
        if key in supplied:
            raise ValueError("duplicate read-set receipt")
        supplied[key] = receipt
    _require_exact_keys("read-set receipts", set(declared), set(supplied))
    for key, declaration in declared.items():
        receipt = supplied[key]
        if receipt.properties != declaration.properties:
            raise ValueError("read-set receipt properties do not match the declaration")
        if receipt.object_count > declaration.max_objects:
            raise ValueError("read-set receipt exceeds max_objects")
        _validate_receipt_state(
            complete=receipt.complete,
            truncated=receipt.truncated,
            observed_at=receipt.observed_at,
            fresh_until=receipt.fresh_until,
            created_at=created_at,
            label="read-set receipt",
        )
    return tuple(supplied[key].receipt_digest for key in sorted(supplied))


def _validate_criterion_results(
    action_type: OntologyActionType,
    results: Sequence[CriterionResult],
    *,
    created_at: datetime,
) -> tuple[str, ...]:
    semantic = action_type.semantic
    if semantic is None:  # pragma: no cover - checked by public function
        raise RuntimeError("semantic contract is unavailable")
    declared = {
        _criterion_key(item.criterion_ref, item.function_ref)
        for item in semantic.submission_criteria
    }
    supplied: dict[tuple[str, str, str], CriterionResult] = {}
    for raw_result in results:
        result = CriterionResult.model_validate(raw_result.model_dump(mode="json"))
        key = _criterion_key(result.criterion_ref, result.function_ref)
        if key in supplied:
            raise ValueError("duplicate CriterionResult receipt")
        supplied[key] = result
    _require_exact_keys("CriterionResult receipts", declared, set(supplied))
    for result in supplied.values():
        if not result.passed:
            raise ValueError("submission criterion did not pass")
        _validate_receipt_state(
            complete=result.complete,
            truncated=result.truncated,
            observed_at=result.observed_at,
            fresh_until=result.fresh_until,
            created_at=created_at,
            label="CriterionResult receipt",
        )
    return tuple(supplied[key].receipt_digest for key in sorted(supplied))


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("action arguments MUST be canonical JSON") from exc


def _reference_key(reference: OntologyDeclarationRef) -> tuple[str, str, str]:
    return reference.name, reference.version, reference.declaration_digest


def _criterion_key(
    criterion_ref: str | None,
    function_ref: OntologyDeclarationRef | None,
) -> tuple[str, str, str]:
    if criterion_ref is not None:
        return "criterion", criterion_ref, ""
    if function_ref is None:
        raise ValueError("CriterionResult requires a declared criterion reference")
    return (
        "function",
        f"{function_ref.name}@{function_ref.version}",
        function_ref.declaration_digest,
    )


def _require_exact_keys(
    label: str,
    declared: set[tuple[str, str, str]],
    supplied: set[tuple[str, str, str]],
) -> None:
    missing = declared - supplied
    if missing:
        raise ValueError(f"{label} are missing declared entries")
    undeclared = supplied - declared
    if undeclared:
        raise ValueError(f"{label} contain undeclared entries")


def _validate_receipt_state(
    *,
    complete: bool,
    truncated: bool,
    observed_at: datetime,
    fresh_until: datetime,
    created_at: datetime,
    label: str,
) -> None:
    if not complete:
        raise ValueError(f"{label} MUST be complete")
    if truncated:
        raise ValueError(f"{label} MUST be untruncated")
    if observed_at > created_at:
        raise ValueError(f"{label} observation is after plan creation")
    if fresh_until < created_at:
        raise ValueError(f"{label} is stale")


def _lock_keys(targets: Sequence[OntologyObjectRecord]) -> tuple[str, ...]:
    return tuple(sorted(f"ontology-target:{target.id}" for target in targets))


def _function_index(
    function_types: Sequence[OntologyFunctionType],
) -> Mapping[tuple[str, str], OntologyFunctionType]:
    result: dict[tuple[str, str], OntologyFunctionType] = {}
    for function_type in function_types:
        key = (function_type.name, function_type.version)
        if key in result:
            raise ValueError(f"duplicate FunctionType declaration {function_type.name!r}")
        result[key] = function_type
    return result


def _validate_semantic_references(
    action_type: OntologyActionType,
    release: OntologyRelease,
    functions: Mapping[tuple[str, str], OntologyFunctionType],
) -> None:
    semantic = action_type.semantic
    if semantic is None:  # pragma: no cover - checked by public function
        raise RuntimeError("semantic contract is unavailable")
    _require_active_ref(semantic.target.type_ref, release, label="action target")
    for parameter in semantic.parameters:
        if parameter.schema_ref is not None:
            _require_active_ref(parameter.schema_ref, release, label="parameter schema")
    for read_set in semantic.read_sets:
        _require_function_kind(
            read_set.function_ref,
            OntologyFunctionKind.QUERY,
            release,
            functions,
            label="read-set",
        )
    for criterion in semantic.submission_criteria:
        if criterion.function_ref is not None:
            _require_function_kind(
                criterion.function_ref,
                OntologyFunctionKind.VALIDATE,
                release,
                functions,
                label="submission criterion",
            )
    _require_function_kind(
        semantic.planner_ref,
        OntologyFunctionKind.PLAN,
        release,
        functions,
        label="planner",
    )
    for postcondition in semantic.postconditions:
        if postcondition.function_ref is not None:
            _require_function_kind(
                postcondition.function_ref,
                OntologyFunctionKind.VALIDATE,
                release,
                functions,
                label="postcondition",
            )


def _require_active_ref(
    reference: OntologyDeclarationRef,
    release: OntologyRelease,
    *,
    label: str,
) -> None:
    if reference not in release.declarations:
        raise ValueError(f"{label} reference is stale or absent from the active ontology release")


def _require_function_kind(
    reference: OntologyDeclarationRef,
    expected_kind: OntologyFunctionKind,
    release: OntologyRelease,
    functions: Mapping[tuple[str, str], OntologyFunctionType],
    *,
    label: str,
) -> None:
    _require_active_ref(reference, release, label=label)
    try:
        declaration = functions[(reference.name, reference.version)]
    except KeyError as exc:
        raise ValueError(f"{label} FunctionType declaration is unavailable") from exc
    supplied_ref = build_ontology_release(function_types=(declaration,)).declarations[0]
    if supplied_ref != reference:
        raise ValueError(f"{label} FunctionType does not match the active ontology release")
    if declaration.kind is not expected_kind:
        raise ValueError(f"{label} FunctionType MUST have kind {expected_kind.value}")


def _validate_targets(
    action_type: OntologyActionType,
    release: OntologyRelease,
    targets: Sequence[OntologyObjectRecord],
    interfaces: CompiledInterfaceCatalog | None,
) -> None:
    semantic = action_type.semantic
    if semantic is None:  # pragma: no cover - checked by public function
        raise RuntimeError("semantic contract is unavailable")
    count = len(targets)
    maximum = semantic.transaction_policy.max_affected_objects
    if not 1 <= count <= maximum:
        raise ValueError("mutation target count exceeds the ActionType transaction bound")
    if semantic.target.cardinality is ActionTargetCardinality.ONE and count != 1:
        raise ValueError("one-cardinality ActionType requires exactly one mutation target")
    target_ids = {target.id for target in targets}
    if len(target_ids) != count:
        raise ValueError("mutation targets MUST have unique object ids")

    selector = semantic.target.type_ref
    concrete_types: tuple[str, ...] | None = None
    if selector.kind is OntologyDeclarationKind.INTERFACE:
        if interfaces is None:
            raise ValueError("InterfaceType ActionType target requires compiled interfaces")
        concrete_types = interfaces.resolve(selector.name)
    for target in targets:
        if target.type_ref is None:
            raise ValueError("mutation targets MUST carry exact type refs")
        expected_ref = release.type_ref(OntologyDeclarationKind.OBJECT, target.object_type)
        if target.type_ref != expected_ref:
            raise ValueError("mutation target type_ref is stale or from another ontology release")
        if selector.kind is OntologyDeclarationKind.OBJECT:
            if target.object_type != selector.name or target.type_ref.version != selector.version:
                raise ValueError(
                    "mutation target does not match the ActionType ObjectType selector"
                )
        elif concrete_types is not None and target.object_type not in concrete_types:
            raise ValueError("mutation target does not implement the ActionType InterfaceType")


def _validate_effects(
    action_type: OntologyActionType,
    targets: Sequence[OntologyObjectRecord],
    effects: Sequence[MutationEffect],
    rollback_effects: Sequence[MutationEffect],
    expected_effects: Sequence[MutationEffect],
) -> None:
    semantic = action_type.semantic
    if semantic is None:  # pragma: no cover - checked by public function
        raise RuntimeError("semantic contract is unavailable")
    target_ids = {target.id for target in targets}
    all_effects = (*effects, *rollback_effects, *expected_effects)
    if any(effect.target_id not in target_ids for effect in all_effects):
        raise ValueError("MutationPlan effects MUST stay within the selected target set")

    target_keys = tuple(sorted(target_ids))
    declared_effects = {item.effect_id: item for item in semantic.effects}
    forward = _indexed_effects("forward effects", effects)
    expected_forward = {
        (effect_id, target_id) for effect_id in declared_effects for target_id in target_keys
    }
    _require_effect_keys("forward effects", expected_forward, set(forward))
    for (effect_id, _target_id), effect in forward.items():
        declaration = declared_effects[effect_id]
        if effect.kind.value != declaration.kind.value:
            raise ValueError("forward effect kind does not match ActionEffectSpec")
        if not effect.command_ref:
            raise ValueError("MutationPlan effect requires exact operation command_ref")
        if effect.command_ref != declaration.operation_ref:
            raise ValueError("forward effect command_ref does not match operation_ref")

    rollback = _indexed_effects("rollback effects", rollback_effects)
    declared_rollbacks = {
        (effect.effect_id, target_id)
        for effect in semantic.effects
        if effect.rollback_operation_ref is not None
        for target_id in target_keys
    }
    if not action_type.irreversible and declared_rollbacks != expected_forward:
        raise ValueError("reversible ActionType lacks rollback operation coverage")
    _require_effect_keys("rollback effects", declared_rollbacks, set(rollback))
    for (effect_id, _target_id), effect in rollback.items():
        declaration = declared_effects[effect_id]
        if effect.kind.value != declaration.kind.value:
            raise ValueError("rollback effect kind does not match ActionEffectSpec")
        if effect.command_ref != declaration.rollback_operation_ref:
            raise ValueError("rollback effect command_ref does not match rollback_operation_ref")

    declared_postconditions = {item.postcondition_id: item for item in semantic.postconditions}
    expected = _indexed_effects("expected effects", expected_effects)
    expected_postconditions = {
        (postcondition_id, target_id)
        for postcondition_id in declared_postconditions
        for target_id in target_keys
    }
    _require_effect_keys("expected effects", expected_postconditions, set(expected))
    for (postcondition_id, _target_id), effect in expected.items():
        postcondition = declared_postconditions[postcondition_id]
        if postcondition.kind is ActionPostconditionKind.PROPERTY:
            if effect.kind is not MutationEffectKind.EXPECTED_PROPERTY:
                raise ValueError("property postcondition requires expected_property effect")
            if effect.observation_ref != postcondition.observation_ref:
                raise ValueError("expected effect observation_ref does not match postcondition")
            prefix = "property."
            if not postcondition.observation_ref or not postcondition.observation_ref.startswith(
                prefix
            ):
                raise ValueError("property postcondition observation_ref MUST use property.<name>")
            if effect.property_name != postcondition.observation_ref.removeprefix(prefix):
                raise ValueError("expected effect property_name does not match observation_ref")
        elif postcondition.kind is ActionPostconditionKind.FUNCTION:
            if effect.kind is not MutationEffectKind.EXPECTED_OBSERVATION:
                raise ValueError("function postcondition requires expected_observation effect")
            if effect.function_ref != postcondition.function_ref:
                raise ValueError("expected effect function_ref does not match postcondition")
        else:
            if effect.kind is not MutationEffectKind.EXPECTED_OBSERVATION:
                raise ValueError("non-property postcondition requires expected_observation effect")
            if effect.observation_ref != postcondition.observation_ref:
                raise ValueError("expected effect observation_ref does not match postcondition")


def _indexed_effects(
    label: str,
    effects: Sequence[MutationEffect],
) -> dict[tuple[str, str], MutationEffect]:
    indexed: dict[tuple[str, str], MutationEffect] = {}
    for effect in effects:
        if effect.effect_id is None:
            raise ValueError(f"{label} require effect_id declaration binding")
        key = (effect.effect_id, effect.target_id)
        if key in indexed:
            raise ValueError(f"duplicate {label} binding")
        indexed[key] = effect
    return indexed


def _require_effect_keys(
    label: str,
    declared: set[tuple[str, str]],
    supplied: set[tuple[str, str]],
) -> None:
    if supplied - declared:
        raise ValueError(f"{label} contain undeclared effects")
    if declared - supplied:
        if label == "rollback effects":
            raise ValueError("rollback effects MUST cover every forward effect")
        raise ValueError(f"{label} are missing declared effects")


def _planner_identity(reference: OntologyDeclarationRef) -> str:
    return f"{reference.name}@{reference.version}:{reference.declaration_digest}"


__all__ = ["compile_action_mutation_plan"]
