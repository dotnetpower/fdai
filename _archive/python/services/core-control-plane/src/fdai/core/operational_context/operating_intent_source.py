"""Fail-closed admission for the deployment-owned six-type operating-intent source.

`ServiceObjective`, `RecoveryObjective`, `CostObjective`, `ArchitectureConstraint`,
`Ownership`, and `ChangeWindow` are the operating-intent ObjectTypes Forseti and the
risk gate read as protected objectives and constraints. Unlike the generic
`FDAI_OPERATING_MODEL_PATH` snapshot (which may legitimately carry only `Resource`
instances), a source presented specifically as the operating-intent binding MUST
supply every required type at its deployment-pinned exact revision and provenance, or
the runtime MUST reject the whole attempt rather than project a partial, duplicated,
expired, or cross-release graph.

Time is handled on two independent axes here. The *effective interval* of an instance
says when its declared intent applies; the *freshness* of the source says how recently
it was actually retrieved. The pinned whole-document digest covers the provenance block
that anchors the second axis, so neither axis can be rewritten without failing the pin.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.operating_model import (
    REQUIRED_OPERATING_INTENT_OBJECT_TYPES,
    OperatingIntentSourceDocument,
    OperatingIntentSourceProvenance,
    operating_intent_source_document_digest,
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class OperatingIntentSourceError(RuntimeError):
    """The deployment-owned operating-intent source failed one fail-closed check.

    Raised instead of projecting anything, so the caller preserves whatever
    operating-intent graph is already durably owned rather than replacing it with a
    missing, duplicate, stale, or cross-release attempt.
    """


@dataclass(frozen=True, slots=True)
class OperatingIntentSourceBinding:
    """The exact, operator-pinned expectation a candidate source MUST satisfy.

    ``expected_revision`` and ``expected_sha256`` are decided once, out of band, when
    an operator reviews and approves a source generation (mirroring
    ``ConfigurationDriftService``'s frozen baseline binding); a later file that
    disagrees with either is evidence of a cross-release swap or a tampered file, not
    a newer approved release. ``expected_sha256`` is the *whole-document* digest,
    provenance included. ``expected_instance_counts`` defaults every required type to
    exactly one instance and is enforced exactly - both a surplus and a shortfall fail
    closed - so a fork that reviews and pins two instances of a type never silently
    accepts one.
    """

    expected_revision: str
    expected_sha256: str
    expected_instance_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.expected_revision.strip():
            raise ValueError("OperatingIntentSourceBinding.expected_revision MUST be non-empty")
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise ValueError("OperatingIntentSourceBinding.expected_sha256 MUST be SHA-256")
        for object_type, count in self.expected_instance_counts.items():
            if object_type not in REQUIRED_OPERATING_INTENT_OBJECT_TYPES:
                raise ValueError(
                    f"expected_instance_counts key {object_type!r} is not a required "
                    "operating-intent ObjectType"
                )
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError(
                    f"expected_instance_counts[{object_type!r}] MUST be a positive integer"
                )

    def expected_count(self, object_type: str) -> int:
        return self.expected_instance_counts.get(object_type, 1)


def validate_operating_intent_source_document(
    document: OperatingIntentSourceDocument,
    *,
    binding: OperatingIntentSourceBinding,
    now: datetime,
) -> None:
    """Fail closed unless the source is exactly the pinned, complete, current graph.

    Checked in fixed priority order so one violated source always reports its
    highest-priority defect first: cross-release identity (revision, self-declared
    provenance, whole-document digest), then required-type instance counts, then
    stale instances. ``now`` MUST be supplied by the caller (never read from the wall
    clock here) so this check stays deterministic under test.
    """

    if now.tzinfo is None:
        raise ValueError("operating intent source validation 'now' MUST be timezone-aware")
    snapshot = document.snapshot
    provenance = document.provenance
    if snapshot.source_revision != binding.expected_revision:
        raise OperatingIntentSourceError(
            "operating intent source revision does not match the configured binding (cross-release)"
        )
    if provenance.resolved_ref != binding.expected_revision:
        raise OperatingIntentSourceError(
            "operating intent source provenance.resolved_ref does not match the configured "
            "binding (cross-release)"
        )
    digest = operating_intent_source_document_digest(document)
    if digest != binding.expected_sha256:
        raise OperatingIntentSourceError(
            "operating intent source content digest does not match the configured binding "
            "(cross-release or tampered source)"
        )
    if provenance.retrieved_at > now:
        raise OperatingIntentSourceError(
            "operating intent source provenance.retrieved_at is in the future (untrusted "
            "observation time)"
        )

    by_type: dict[str, list[OntologyObjectRecord]] = {}
    for item in snapshot.objects:
        by_type.setdefault(item.object_type, []).append(item)
    unexpected_types = sorted(set(by_type) - REQUIRED_OPERATING_INTENT_OBJECT_TYPES)
    if unexpected_types:
        raise OperatingIntentSourceError(
            "operating intent source contains non-operating-intent ObjectTypes "
            f"{unexpected_types!r}"
        )

    for object_type in sorted(REQUIRED_OPERATING_INTENT_OBJECT_TYPES):
        count = len(by_type.get(object_type, ()))
        if count == 0:
            raise OperatingIntentSourceError(
                f"operating intent source is missing required type {object_type!r}"
            )
        expected = binding.expected_count(object_type)
        if count != expected:
            defect = "duplicate" if count > expected else "incomplete"
            raise OperatingIntentSourceError(
                f"operating intent source has {count} instances of {object_type!r}, "
                f"expected exactly {expected} ({defect})"
            )

    for object_type in sorted(REQUIRED_OPERATING_INTENT_OBJECT_TYPES):
        for item in sorted(by_type[object_type], key=lambda record: record.id):
            _reject_if_stale(item, provenance=provenance, now=now)


def _reject_if_stale(
    item: OntologyObjectRecord,
    *,
    provenance: OperatingIntentSourceProvenance,
    now: datetime,
) -> None:
    """Reject an instance that is outside its effective interval or no longer fresh.

    These are two independent time axes and MUST NOT be conflated. The effective
    interval (``effective_from``/``effective_to``) is *when the declared intent
    applies*: an objective approved years ago and still in force is perfectly current.
    Freshness is *how recently the source was actually observed*, so it is measured
    from the document's trusted ``provenance.retrieved_at`` - which the pinned
    whole-document digest covers, so it cannot be forward-dated without failing the
    pin first. Measuring freshness from ``effective_from`` instead would call every
    long-lived objective stale while accepting a stale re-publication of a
    newly-effective one.
    """

    effective_from = _required_datetime(item, "effective_from")
    effective_to = _optional_datetime(item, "effective_to")
    if effective_from > now or (effective_to is not None and now >= effective_to):
        raise OperatingIntentSourceError(
            f"operating intent source instance {item.id!r} ({item.object_type}) is not "
            "currently effective (stale)"
        )
    freshness_seconds = item.properties.get("freshness_seconds")
    if freshness_seconds is None:
        return
    if isinstance(freshness_seconds, bool) or not isinstance(freshness_seconds, int):
        raise OperatingIntentSourceError(
            f"operating intent source instance {item.id!r} ({item.object_type}) "
            "freshness_seconds MUST be an integer"
        )
    if (now - provenance.retrieved_at).total_seconds() > freshness_seconds:
        raise OperatingIntentSourceError(
            f"operating intent source instance {item.id!r} ({item.object_type}) exceeds its "
            "declared freshness_seconds since the source was retrieved (stale)"
        )


def _required_datetime(item: OntologyObjectRecord, key: str) -> datetime:
    value = _optional_datetime(item, key)
    if value is None:
        raise OperatingIntentSourceError(
            f"operating intent source instance {item.id!r} ({item.object_type}) is missing "
            f"required property {key!r}"
        )
    return value


def _optional_datetime(item: OntologyObjectRecord, key: str) -> datetime | None:
    raw = item.properties.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise OperatingIntentSourceError(
            f"operating intent source instance {item.id!r} ({item.object_type}) property "
            f"{key!r} MUST be an RFC 3339 timestamp string"
        )
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise OperatingIntentSourceError(
            f"operating intent source instance {item.id!r} ({item.object_type}) property "
            f"{key!r} MUST be an RFC 3339 timestamp string"
        ) from exc
    if value.tzinfo is None:
        raise OperatingIntentSourceError(
            f"operating intent source instance {item.id!r} ({item.object_type}) property "
            f"{key!r} MUST be timezone-aware"
        )
    return value


__all__ = [
    "OperatingIntentSourceBinding",
    "OperatingIntentSourceError",
    "validate_operating_intent_source_document",
]
