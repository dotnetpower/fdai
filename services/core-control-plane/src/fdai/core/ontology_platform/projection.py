"""Pure source projection and effect reconciliation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai.shared.contracts.models import OntologyRelease
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .kinetics import (
    MutationEffectKind,
    MutationPlan,
    ProjectedBatch,
    ProjectionBinding,
    ReconciliationReceipt,
    ReconciliationStatus,
)


def project_source_records(
    *,
    binding: ProjectionBinding,
    records: Sequence[Mapping[str, Any]],
    release: OntologyRelease,
) -> ProjectedBatch:
    if len(records) > binding.max_batch_size:
        raise ValueError("projection batch exceeds binding max_batch_size")
    expected_ref = release.type_ref(
        binding.object_type_ref.kind,
        binding.object_type_ref.name,
    )
    if expected_ref != binding.object_type_ref:
        raise ValueError("projection binding type ref is not in the active release")
    projected = []
    deleted_ids = []
    seen_ids: set[str] = set()
    watermarks: list[str] = []
    for raw in records:
        identity = raw.get(binding.identity_field)
        watermark = raw.get(binding.watermark_field)
        if not isinstance(identity, str) or not identity:
            raise ValueError("projection record identity is missing")
        if identity in seen_ids:
            raise ValueError(f"projection {binding.binding_id!r} has duplicate identity")
        seen_ids.add(identity)
        if not isinstance(watermark, str) or not watermark:
            raise ValueError("projection record watermark is missing")
        try:
            parsed_watermark = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("projection record watermark MUST be RFC3339") from exc
        if parsed_watermark.tzinfo is None:
            raise ValueError("projection record watermark MUST be timezone-aware")
        if binding.delete_field is not None and binding.delete_field in raw:
            delete_marker = raw[binding.delete_field]
            if not isinstance(delete_marker, bool):
                raise ValueError("projection record delete marker MUST be boolean")
            if delete_marker:
                deleted_ids.append(identity)
                watermarks.append(watermark)
                continue
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
    return ProjectedBatch(
        objects=tuple(projected),
        deleted_ids=tuple(sorted(deleted_ids)),
        watermark=max(watermarks, default=None),
    )


def reconcile_expected_effects(
    *,
    plan: MutationPlan,
    observed: Mapping[str, OntologyObjectRecord],
    observed_at: datetime,
    deadline: datetime,
    evidence_refs: tuple[str, ...],
) -> ReconciliationReceipt:
    if observed_at.tzinfo is None:
        raise ValueError("reconciliation observed_at MUST be timezone-aware")
    if deadline.tzinfo is None:
        raise ValueError("reconciliation deadline MUST be timezone-aware")
    if observed_at > deadline:
        return ReconciliationReceipt(
            plan_digest=plan.digest,
            status=ReconciliationStatus.TIMED_OUT,
            observed_at=observed_at,
            evidence_refs=evidence_refs,
        )
    if not plan.expected_effects:
        return ReconciliationReceipt(
            plan_digest=plan.digest,
            status=ReconciliationStatus.UNSCORABLE,
            observed_at=observed_at,
            evidence_refs=evidence_refs,
        )
    mismatches = []
    for effect in plan.expected_effects:
        if effect.kind is not MutationEffectKind.EXPECTED_PROPERTY:
            continue
        record = observed.get(effect.target_id)
        if record is None or effect.property_name is None:
            mismatches.append(f"{effect.target_id}:unobserved")
            continue
        if not _json_values_equal(record.properties.get(effect.property_name), effect.value):
            mismatches.append(f"{effect.target_id}:{effect.property_name}")
    status = ReconciliationStatus.MISMATCHED if mismatches else ReconciliationStatus.MATCHED
    return ReconciliationReceipt(
        plan_digest=plan.digest,
        status=status,
        observed_at=observed_at,
        evidence_refs=evidence_refs,
        mismatches=tuple(mismatches),
    )


def _json_values_equal(left: object, right: object) -> bool:
    """Compare canonical JSON encodings so booleans never equal integers."""

    return _canonical_json_bytes(left) == _canonical_json_bytes(right)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = ["project_source_records", "reconcile_expected_effects"]
