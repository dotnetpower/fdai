"""Pure ActionType semantic compilation into proposal-only mutation plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai.shared.contracts.models import (
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

from .interfaces import CompiledInterfaceCatalog
from .kinetics import MutationEffect, MutationEffectKind, MutationPlan
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
        if effects or rollback_effects or expected_effects or created_at is not None:
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
        )
        if candidate != existing_plan:
            raise ValueError("existing MutationPlan does not match the active ActionType contract")
        return existing_plan

    if created_at is None:
        raise ValueError("semantic mutation-plan compilation requires created_at")
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
    )


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

    declared_kinds = {effect.kind.value for effect in semantic.effects}
    for effect in (*effects, *rollback_effects):
        if effect.kind is MutationEffectKind.EXPECTED_PROPERTY:
            raise ValueError("expected-property effects belong in expected_effects")
        if effect.kind.value not in declared_kinds:
            raise ValueError(f"MutationPlan effect kind {effect.kind.value!r} is not declared")
    if expected_effects and not any(
        item.kind is ActionPostconditionKind.PROPERTY for item in semantic.postconditions
    ):
        raise ValueError("expected property effects require a declared property postcondition")
    if any(effect.kind is not MutationEffectKind.EXPECTED_PROPERTY for effect in expected_effects):
        raise ValueError("expected_effects accepts only expected_property effects")


def _planner_identity(reference: OntologyDeclarationRef) -> str:
    return f"{reference.name}@{reference.version}:{reference.declaration_digest}"


__all__ = ["compile_action_mutation_plan"]
