"""Deterministic mutation-plan construction and stale-plan checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai.shared.contracts.models import ActionLockScope, ActionTransactionMode, OntologyTypeRef
from fdai.shared.providers.ontology_instance import (
    OntologyObjectRecord,
    canonical_json_mapping,
)

from .kinetics import ActionArgumentBinding, MutationEffect, MutationPlan, TargetRevision


def build_mutation_plan(
    *,
    action_type_ref: OntologyTypeRef,
    planner_ref: str,
    targets: Sequence[OntologyObjectRecord],
    effects: Sequence[MutationEffect],
    rollback_effects: Sequence[MutationEffect],
    expected_effects: Sequence[MutationEffect] = (),
    created_at: datetime,
    max_affected_objects: int,
    schema_version: str = "1.0.0",
    arguments_digest: str | None = None,
    argument_bindings: Sequence[ActionArgumentBinding] = (),
    read_set_receipt_digests: Sequence[str] = (),
    criterion_receipt_digests: Sequence[str] = (),
    transaction_mode: ActionTransactionMode | None = None,
    lock_scope: ActionLockScope | None = None,
    lock_keys: Sequence[str] = (),
    irreversible: bool = False,
) -> MutationPlan:
    if not 1 <= len(targets) <= max_affected_objects:
        raise ValueError("mutation target count exceeds the declared impact limit")
    pinned = []
    for target in sorted(targets, key=lambda item: item.id):
        if target.type_ref is None or target.revision < 1:
            raise ValueError("mutation targets MUST carry exact type refs and revisions")
        pinned.append(
            TargetRevision(
                object_id=target.id,
                type_ref=target.type_ref,
                revision=target.revision,
            )
        )
    material = {
        "action_type_ref": action_type_ref.model_dump(mode="json"),
        "planner_ref": planner_ref,
        "targets": [item.model_dump(mode="json") for item in pinned],
        "effects": [_effect_dump(item) for item in effects],
        "rollback_effects": [_effect_dump(item) for item in rollback_effects],
        "expected_effects": [_effect_dump(item) for item in expected_effects],
        "arguments_digest": arguments_digest,
        "argument_bindings": [item.model_dump(mode="json") for item in argument_bindings],
        "read_set_receipt_digests": list(read_set_receipt_digests),
        "criterion_receipt_digests": list(criterion_receipt_digests),
        "transaction_mode": transaction_mode.value if transaction_mode is not None else None,
        "lock_scope": lock_scope.value if lock_scope is not None else None,
        "lock_keys": list(lock_keys),
        "max_affected_objects": max_affected_objects if schema_version == "2.0.0" else None,
        "irreversible": irreversible,
    }
    digest = _digest(material)
    return MutationPlan(
        schema_version=schema_version,
        plan_id=f"mutation-plan:{digest.removeprefix('sha256:')}",
        digest=digest,
        action_type_ref=action_type_ref,
        planner_ref=planner_ref,
        targets=tuple(pinned),
        effects=tuple(effects),
        rollback_effects=tuple(rollback_effects),
        expected_effects=tuple(expected_effects),
        created_at=created_at,
        arguments_digest=arguments_digest,
        argument_bindings=tuple(argument_bindings),
        read_set_receipt_digests=tuple(read_set_receipt_digests),
        criterion_receipt_digests=tuple(criterion_receipt_digests),
        transaction_mode=transaction_mode,
        lock_scope=lock_scope,
        lock_keys=tuple(lock_keys),
        max_affected_objects=(max_affected_objects if schema_version == "2.0.0" else None),
        irreversible=irreversible,
    )


def validate_plan_revisions(
    plan: MutationPlan,
    current: Mapping[str, OntologyObjectRecord],
) -> None:
    for target in plan.targets:
        observed = current.get(target.object_id)
        if observed is None or observed.revision != target.revision:
            raise ValueError(f"mutation plan target {target.object_id!r} is stale")
        if observed.type_ref != target.type_ref:
            raise ValueError(f"mutation plan target {target.object_id!r} changed type release")


def _effect_dump(effect: MutationEffect) -> dict[str, object]:
    value, _ = canonical_json_mapping(
        effect.model_dump(mode="json", exclude_none=True), path="mutation_effect"
    )
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["build_mutation_plan", "validate_plan_revisions"]
