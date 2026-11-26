"""Strict JSON codec for durable independent effect observation receipts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, cast

from fdai.core.executor.effect_observation import (
    IndependentEffectDisposition,
    IndependentEffectObservationBinding,
    IndependentEffectObservationReceipt,
    IndependentEffectOutcome,
    ObservationCompleteness,
    ObservationContainment,
    ObservationFinality,
    ObservationQuality,
)

_BINDING_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "action_id",
        "action_payload_digest",
        "target_digest",
        "source_revision",
        "execution_path",
        "execution_origin",
        "execution_venue",
        "safeguard_bundle_digest",
        "evidence_identity_digest",
        "evidence_record_digest",
        "evidence_record_revision",
        "executor_receipt_digest",
        "binding_digest",
    }
)

_QUALITY_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "evidence_window_start",
        "evidence_window_end",
        "source_recorded_at",
        "max_source_age_seconds",
        "finality",
        "completeness",
        "containment",
        "conflicting_source_count",
        "synthetic",
    }
)

_RECEIPT_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "observation_id",
        "binding",
        "quality",
        "outcome",
        "disposition",
        "reason",
        "observer_instance_id",
        "executor_instance_id",
        "source_instance_id",
        "observed_at",
        "completed_at",
        "sequence",
        "prior_receipt_digest",
        "receipt_digest",
        "effect_verified",
        "execution_authority",
        "sink_commit_authority",
        "lock_release_authority",
        "promotion_authority",
    }
)


def observation_receipt_to_mapping(
    receipt: IndependentEffectObservationReceipt,
) -> dict[str, object]:
    """Serialize one validated observation receipt to canonical JSON values."""

    if type(receipt) is not IndependentEffectObservationReceipt:
        raise ValueError("independent effect observation serializer requires an exact receipt")
    return {
        "schema_version": receipt.schema_version,
        "binding": _binding_to_mapping(receipt.binding),
        "quality": _quality_to_mapping(receipt.quality),
        "observation_id": receipt.observation_id,
        "outcome": receipt.outcome.value,
        "disposition": receipt.disposition.value,
        "reason": receipt.reason,
        "observer_instance_id": receipt.observer_instance_id,
        "executor_instance_id": receipt.executor_instance_id,
        "source_instance_id": receipt.source_instance_id,
        "observed_at": receipt.observed_at.isoformat(),
        "completed_at": receipt.completed_at.isoformat(),
        "sequence": receipt.sequence,
        "prior_receipt_digest": receipt.prior_receipt_digest,
        "receipt_digest": receipt.receipt_digest,
        "effect_verified": receipt.effect_verified,
        "execution_authority": receipt.execution_authority,
        "sink_commit_authority": receipt.sink_commit_authority,
        "lock_release_authority": receipt.lock_release_authority,
        "promotion_authority": receipt.promotion_authority,
    }


def observation_receipt_from_mapping(
    value: Mapping[str, object],
) -> IndependentEffectObservationReceipt:
    """Parse one exact durable receipt and rerun all semantic invariants."""

    receipt = _exact(value, _RECEIPT_KEYS, "receipt")
    return IndependentEffectObservationReceipt(
        schema_version=_version(receipt),
        observation_id=_text(receipt, "observation_id"),
        binding=_binding_from_mapping(_object(receipt, "binding")),
        quality=_quality_from_mapping(_object(receipt, "quality")),
        outcome=_enum(receipt, "outcome", IndependentEffectOutcome),
        disposition=_enum(receipt, "disposition", IndependentEffectDisposition),
        reason=_text(receipt, "reason"),
        observer_instance_id=_text(receipt, "observer_instance_id"),
        executor_instance_id=_text(receipt, "executor_instance_id"),
        source_instance_id=_text(receipt, "source_instance_id"),
        observed_at=_moment(receipt, "observed_at"),
        completed_at=_moment(receipt, "completed_at"),
        sequence=_integer(receipt, "sequence"),
        prior_receipt_digest=_optional_text(receipt, "prior_receipt_digest"),
        receipt_digest=_text(receipt, "receipt_digest"),
        effect_verified=_boolean(receipt, "effect_verified"),
        execution_authority=_false(receipt, "execution_authority"),
        sink_commit_authority=_false(receipt, "sink_commit_authority"),
        lock_release_authority=_false(receipt, "lock_release_authority"),
        promotion_authority=_false(receipt, "promotion_authority"),
    )


def _binding_to_mapping(
    binding: IndependentEffectObservationBinding,
) -> dict[str, object]:
    return {
        "schema_version": binding.schema_version,
        "action_id": binding.action_id,
        "action_payload_digest": binding.action_payload_digest,
        "target_digest": binding.target_digest,
        "source_revision": binding.source_revision,
        "execution_path": binding.execution_path,
        "execution_origin": binding.execution_origin,
        "execution_venue": binding.execution_venue,
        "safeguard_bundle_digest": binding.safeguard_bundle_digest,
        "evidence_identity_digest": binding.evidence_identity_digest,
        "evidence_record_digest": binding.evidence_record_digest,
        "evidence_record_revision": binding.evidence_record_revision,
        "executor_receipt_digest": binding.executor_receipt_digest,
        "binding_digest": binding.binding_digest,
    }


def _binding_from_mapping(
    value: Mapping[str, object],
) -> IndependentEffectObservationBinding:
    binding = _exact(value, _BINDING_KEYS, "binding")
    return IndependentEffectObservationBinding(
        schema_version=_version(binding),
        action_id=_text(binding, "action_id"),
        action_payload_digest=_text(binding, "action_payload_digest"),
        target_digest=_text(binding, "target_digest"),
        source_revision=_text(binding, "source_revision"),
        execution_path=_text(binding, "execution_path"),
        execution_origin=_text(binding, "execution_origin"),
        execution_venue=_text(binding, "execution_venue"),
        safeguard_bundle_digest=_text(binding, "safeguard_bundle_digest"),
        evidence_identity_digest=_text(binding, "evidence_identity_digest"),
        evidence_record_digest=_text(binding, "evidence_record_digest"),
        evidence_record_revision=_integer(binding, "evidence_record_revision"),
        executor_receipt_digest=_text(binding, "executor_receipt_digest"),
        binding_digest=_text(binding, "binding_digest"),
    )


def _quality_to_mapping(quality: ObservationQuality) -> dict[str, object]:
    return {
        "schema_version": quality.schema_version,
        "evidence_window_start": quality.evidence_window_start.isoformat(),
        "evidence_window_end": quality.evidence_window_end.isoformat(),
        "source_recorded_at": quality.source_recorded_at.isoformat(),
        "max_source_age_seconds": quality.max_source_age_seconds,
        "finality": quality.finality.value,
        "completeness": quality.completeness.value,
        "containment": quality.containment.value,
        "conflicting_source_count": quality.conflicting_source_count,
        "synthetic": quality.synthetic,
    }


def _quality_from_mapping(value: Mapping[str, object]) -> ObservationQuality:
    quality = _exact(value, _QUALITY_KEYS, "quality")
    raw_age = quality.get("max_source_age_seconds")
    if type(raw_age) not in {int, float} or isinstance(raw_age, bool):
        raise ValueError("independent effect observation freshness bound MUST be numeric")
    return ObservationQuality(
        schema_version=_version(quality),
        evidence_window_start=_moment(quality, "evidence_window_start"),
        evidence_window_end=_moment(quality, "evidence_window_end"),
        source_recorded_at=_moment(quality, "source_recorded_at"),
        max_source_age_seconds=cast(float, raw_age),
        finality=_enum(quality, "finality", ObservationFinality),
        completeness=_enum(quality, "completeness", ObservationCompleteness),
        containment=_enum(quality, "containment", ObservationContainment),
        conflicting_source_count=_integer(quality, "conflicting_source_count"),
        synthetic=_boolean(quality, "synthetic"),
    )


def _exact(
    value: Mapping[str, object],
    expected: frozenset[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f"independent effect observation {name} fields are invalid")
    return value


def _object(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    field = value.get(name)
    if type(field) is not dict:
        raise ValueError(f"independent effect observation {name} MUST be an object")
    return cast(dict[str, object], field)


def _text(value: Mapping[str, object], name: str) -> str:
    field = value.get(name)
    if type(field) is not str:
        raise ValueError(f"independent effect observation {name} MUST be a string")
    return field


def _optional_text(value: Mapping[str, object], name: str) -> str | None:
    if value.get(name) is None:
        return None
    return _text(value, name)


def _integer(value: Mapping[str, object], name: str) -> int:
    field = value.get(name)
    if type(field) is not int:
        raise ValueError(f"independent effect observation {name} MUST be an integer")
    return field


def _boolean(value: Mapping[str, object], name: str) -> bool:
    field = value.get(name)
    if type(field) is not bool:
        raise ValueError(f"independent effect observation {name} MUST be a boolean")
    return field


def _false(value: Mapping[str, object], name: str) -> Literal[False]:
    if value.get(name) is not False:
        raise ValueError(f"independent effect observation {name} MUST be false")
    return False


def _moment(value: Mapping[str, object], name: str) -> datetime:
    raw = _text(value, name)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"independent effect observation {name} MUST be an ISO 8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"independent effect observation {name} MUST include a timezone")
    return parsed.astimezone(UTC)


def _version(value: Mapping[str, object]) -> Literal["1.0.0"]:
    if _text(value, "schema_version") != "1.0.0":
        raise ValueError("independent effect observation schema version is unsupported")
    return "1.0.0"


def _enum[EnumT: StrEnum](
    value: Mapping[str, object],
    name: str,
    enum_type: type[EnumT],
) -> EnumT:
    raw = _text(value, name)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise ValueError(f"independent effect observation {name} is invalid") from exc


__all__ = [
    "observation_receipt_from_mapping",
    "observation_receipt_to_mapping",
]
