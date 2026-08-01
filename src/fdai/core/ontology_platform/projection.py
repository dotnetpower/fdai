"""Pure source projection and effect reconciliation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai.shared.contracts.models import OntologyRelease
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .kinetics import (
    MutationEffectKind,
    MutationPlan,
    ProjectionBinding,
    ReconciliationReceipt,
    ReconciliationStatus,
)


def project_source_records(
    *,
    binding: ProjectionBinding,
    records: Sequence[Mapping[str, Any]],
    release: OntologyRelease,
) -> tuple[tuple[OntologyObjectRecord, ...], str | None]:
    if len(records) > binding.max_batch_size:
        raise ValueError("projection batch exceeds binding max_batch_size")
    expected_ref = release.type_ref(
        binding.object_type_ref.kind,
        binding.object_type_ref.name,
    )
    if expected_ref != binding.object_type_ref:
        raise ValueError("projection binding type ref is not in the active release")
    projected = []
    watermarks: list[str] = []
    for raw in records:
        identity = raw.get(binding.identity_field)
        watermark = raw.get(binding.watermark_field)
        if not isinstance(identity, str) or not identity:
            raise ValueError("projection record identity is missing")
        if not isinstance(watermark, str) or not watermark:
            raise ValueError("projection record watermark is missing")
        properties = {
            target: raw[source] for source, target in binding.property_map.items() if source in raw
        }
        projected.append(
            OntologyObjectRecord(
                id=identity,
                object_type=binding.object_type_ref.name,
                properties=properties,
                type_ref=binding.object_type_ref,
            )
        )
        watermarks.append(watermark)
    return tuple(projected), max(watermarks, default=None)


def reconcile_expected_effects(
    *,
    plan: MutationPlan,
    observed: Mapping[str, OntologyObjectRecord],
    observed_at: datetime,
    evidence_refs: tuple[str, ...],
) -> ReconciliationReceipt:
    if observed_at.tzinfo is None:
        raise ValueError("reconciliation observed_at MUST be timezone-aware")
    mismatches = []
    for effect in plan.expected_effects:
        if effect.kind is not MutationEffectKind.EXPECTED_PROPERTY:
            continue
        record = observed.get(effect.target_id)
        if record is None or effect.property_name is None:
            mismatches.append(f"{effect.target_id}:unobserved")
            continue
        if record.properties.get(effect.property_name) != effect.value:
            mismatches.append(f"{effect.target_id}:{effect.property_name}")
    status = ReconciliationStatus.MISMATCHED if mismatches else ReconciliationStatus.MATCHED
    if not plan.expected_effects:
        status = ReconciliationStatus.UNSCORABLE
    return ReconciliationReceipt(
        plan_digest=plan.digest,
        status=status,
        observed_at=observed_at,
        evidence_refs=evidence_refs,
        mismatches=tuple(mismatches),
    )


__all__ = ["project_source_records", "reconcile_expected_effects"]
