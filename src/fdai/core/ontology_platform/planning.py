"""Deterministic mutation-plan construction and stale-plan checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai.shared.contracts.models import OntologyTypeRef
from fdai.shared.providers.ontology_instance import (
    OntologyObjectRecord,
    canonical_json_mapping,
)

from .kinetics import MutationEffect, MutationPlan, TargetRevision


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
    }
    digest = _digest(material)
    return MutationPlan(
        plan_id=f"mutation-plan:{digest.removeprefix('sha256:')}",
        digest=digest,
        action_type_ref=action_type_ref,
        planner_ref=planner_ref,
        targets=tuple(pinned),
        effects=tuple(effects),
        rollback_effects=tuple(rollback_effects),
        expected_effects=tuple(expected_effects),
        created_at=created_at,
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
