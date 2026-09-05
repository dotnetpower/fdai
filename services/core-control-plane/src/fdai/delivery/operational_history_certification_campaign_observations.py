"""Build the bounded dev-only synthetic observations the OI-16 campaign observes.

The campaign cannot certify operational history it never wrote. Every synthetic
record here is a real :class:`NormalizedInventoryObservation` that the existing
PostgreSQL journal adapter appends and that
:func:`fdai.delivery.persistence.postgres_observation_lifecycle.bind_observation_lifecycle`
binds to a real partition and a real resource incarnation. This module never issues
SQL, never writes a partition, a checkpoint, or an incarnation directly, and never
addresses a scope outside the synthetic certification prefix.

Every field that reaches a content digest is a pure function of the synthetic scope
and, where a per-campaign target is required, the campaign id. Repeating one campaign
therefore converges on the identical observation identities, so the journal reports a
suppressed replay instead of a second insert.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from fdai.delivery.operational_history_certification_campaign import (
    CampaignBinding,
    evidence_digest,
)
from fdai.shared.providers.inventory_observation import (
    INVENTORY_OBSERVATION_SCHEMA_VERSION,
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)

OBSERVATION_EPOCH = datetime(2024, 1, 1, 12, tzinfo=UTC)
PRIOR_SCHEMA_VERSION = "0.9.0"
SYNTHETIC_SOURCE_IDENTITY = "fdai-oi16-campaign"
SYNTHETIC_SUBJECT_TYPE = "synthetic_operational_probe"
SYNTHETIC_PROVIDER_REF = "fdai-oi16-campaign-provider"
LATE_OFFSET = timedelta(hours=6)

_PRIOR_ABSENT_FIELDS = (
    "property_mask",
    "scope_ref",
    "operation",
    "operation_status",
    "tombstone_confirmed",
)
_UNRECOVERABLE_FIELDS = (
    "scope_ref",
    "operation",
    "operation_status",
    "tombstone_confirmed",
)
_JOURNAL_ONLY_FIELDS = ("watermark", "recorded_at")


class SyntheticSlot(StrEnum):
    """One bounded synthetic history slot the campaign prepares and observes."""

    WARM = "warm"
    PURGE = "purge"
    HELD = "held"
    PRIOR = "prior"
    CORRECTION = "correction"
    INCARNATION = "incarnation"


PER_CAMPAIGN_SLOTS = frozenset({SyntheticSlot.PURGE})
_SLOT_DAYS: Mapping[SyntheticSlot, int] = {
    SyntheticSlot.WARM: 0,
    SyntheticSlot.PURGE: 1,
    SyntheticSlot.HELD: 2,
    SyntheticSlot.PRIOR: 3,
    SyntheticSlot.CORRECTION: 4,
    SyntheticSlot.INCARNATION: 5,
}


class CampaignObservationJournal(Protocol):
    """Append normalized observations through the deployed journal adapter."""

    async def append_change_batch(
        self, observations: Sequence[NormalizedInventoryObservation]
    ) -> Any: ...


def slot_effective_at(slot: SyntheticSlot, *, index: int = 0) -> datetime:
    """Return the deterministic effective time one synthetic slot record carries."""

    return OBSERVATION_EPOCH + timedelta(days=_SLOT_DAYS[slot] + index)


def synthetic_resource_ref(binding: CampaignBinding, slot: SyntheticSlot) -> str:
    """Return the exact synthetic resource identity one slot observes."""

    return f"{binding.scope.scope_ref}/resource/{slot.value}"


def slot_idempotency_key(binding: CampaignBinding, slot: SyntheticSlot, *, index: int = 0) -> str:
    """Return the stable delivery identity for one synthetic slot record.

    A per-campaign slot mixes the campaign id into the key so each campaign owns the
    exact record it is allowed to destroy. Every other slot keeps a campaign
    independent key, so a repeated campaign replays it instead of duplicating it.
    """

    material: dict[str, object] = {
        "scope": binding.scope.digest,
        "slot": slot.value,
        "index": index,
    }
    if slot in PER_CAMPAIGN_SLOTS:
        material["campaign"] = binding.campaign_id
    return "oi16-" + evidence_digest(material).removeprefix("sha256:")


def full_observation(
    binding: CampaignBinding,
    slot: SyntheticSlot,
    *,
    index: int = 0,
    effective_at: datetime | None = None,
) -> NormalizedInventoryObservation:
    """Build one complete synthetic object observation for a bounded slot."""

    moment = slot_effective_at(slot, index=index) if effective_at is None else effective_at
    properties = {"slot": slot.value, "sequence": index, "synthetic": True}
    return NormalizedInventoryObservation.create(
        idempotency_key=slot_idempotency_key(binding, slot, index=index),
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.FULL,
        mutation_kind=InventoryMutationKind.UPSERT,
        subject_ref=synthetic_resource_ref(binding, slot),
        subject_type=SYNTHETIC_SUBJECT_TYPE,
        properties=properties,
        property_mask=tuple(sorted(properties)),
        properties_complete=True,
        links_complete=True,
        tombstone_confirmed=False,
        provider_ref=SYNTHETIC_PROVIDER_REF,
        scope_ref=binding.scope.scope_ref,
        source_identity=SYNTHETIC_SOURCE_IDENTITY,
        source_event_id=slot_idempotency_key(binding, slot, index=index),
        source_revision=binding.source_revision,
        effective_at=moment,
        observed_at=moment,
        evidence_cutoff=moment,
        recorded_at=moment,
    )


def late_observation(binding: CampaignBinding) -> NormalizedInventoryObservation:
    """Build the out-of-order arrival that MUST open a real correction partition.

    The record is effective before the slot's own base observation and inside the same
    day-aligned interval, so the deployed lifecycle binder classifies it as late and
    attaches it to the base partition it corrects.
    """

    return full_observation(
        binding,
        SyntheticSlot.CORRECTION,
        index=1,
        effective_at=slot_effective_at(SyntheticSlot.CORRECTION) - LATE_OFFSET,
    )


def confirmed_tombstone(binding: CampaignBinding, *, index: int) -> NormalizedInventoryObservation:
    """Build the confirmed deletion that MUST close a persisted incarnation."""

    moment = slot_effective_at(SyntheticSlot.INCARNATION, index=index)
    return NormalizedInventoryObservation.create(
        idempotency_key=slot_idempotency_key(binding, SyntheticSlot.INCARNATION, index=index),
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.TOMBSTONE,
        mutation_kind=InventoryMutationKind.DELETE,
        subject_ref=synthetic_resource_ref(binding, SyntheticSlot.INCARNATION),
        subject_type=SYNTHETIC_SUBJECT_TYPE,
        properties={},
        property_mask=(),
        properties_complete=False,
        links_complete=False,
        tombstone_confirmed=True,
        provider_ref=SYNTHETIC_PROVIDER_REF,
        scope_ref=binding.scope.scope_ref,
        source_identity=SYNTHETIC_SOURCE_IDENTITY,
        source_event_id=slot_idempotency_key(binding, SyntheticSlot.INCARNATION, index=index),
        source_revision=binding.source_revision,
        effective_at=moment,
        observed_at=moment,
        evidence_cutoff=moment,
        recorded_at=moment,
    )


def incarnation_lifecycle(
    binding: CampaignBinding,
) -> tuple[
    NormalizedInventoryObservation,
    NormalizedInventoryObservation,
    NormalizedInventoryObservation,
]:
    """Return the open, confirmed-delete, and reopen arrivals in arrival order."""

    return (
        full_observation(binding, SyntheticSlot.INCARNATION, index=0),
        confirmed_tombstone(binding, index=1),
        full_observation(binding, SyntheticSlot.INCARNATION, index=2),
    )


def downgrade_to_prior_schema(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the N-1 form of one persisted normalized record.

    The N-1 release predates the property mask, the observation scope, the provider
    operation pair, and confirmed tombstones, so those fields are absent rather than
    empty. Everything else is carried unchanged, which is what makes the archived
    record a genuine N-1 record instead of a relabelled current record.
    """

    if record.get("schema_version") != INVENTORY_OBSERVATION_SCHEMA_VERSION:
        raise ValueError("only a current-release record can be downgraded to N-1")
    downgraded = {
        key: value
        for key, value in record.items()
        if key not in _PRIOR_ABSENT_FIELDS and key not in _JOURNAL_ONLY_FIELDS
    }
    downgraded["schema_version"] = PRIOR_SCHEMA_VERSION
    return downgraded


def cross_release_stable_body(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the fields a schema release transform MUST NOT silently change."""

    return {
        key: value
        for key, value in record.items()
        if key not in _UNRECOVERABLE_FIELDS and key not in _JOURNAL_ONLY_FIELDS
    }


def prior_schema_record(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Return the first archived N-1 record, or ``None`` when none was archived."""

    for record in records:
        if record.get("schema_version") == PRIOR_SCHEMA_VERSION:
            return record
    return None


def current_schema_record(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Return the first persisted current-release record, or ``None``."""

    for record in records:
        if record.get("schema_version") == INVENTORY_OBSERVATION_SCHEMA_VERSION:
            return record
    return None


__all__ = [
    "LATE_OFFSET",
    "OBSERVATION_EPOCH",
    "PER_CAMPAIGN_SLOTS",
    "PRIOR_SCHEMA_VERSION",
    "SYNTHETIC_PROVIDER_REF",
    "SYNTHETIC_SOURCE_IDENTITY",
    "SYNTHETIC_SUBJECT_TYPE",
    "CampaignObservationJournal",
    "SyntheticSlot",
    "confirmed_tombstone",
    "cross_release_stable_body",
    "current_schema_record",
    "downgrade_to_prior_schema",
    "full_observation",
    "incarnation_lifecycle",
    "late_observation",
    "prior_schema_record",
    "slot_effective_at",
    "slot_idempotency_key",
    "synthetic_resource_ref",
]
