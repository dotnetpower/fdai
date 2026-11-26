"""Bind F06.2 qualification evidence to one installation and reconcile it with the ledger.

The record is review-only. It names what was measured, against which exact revisions and cutoff,
and why it is not ready when it is not. It never grants activation, approval, or execution
authority and never changes a mode.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.rule_catalog.schema.framework_assessment import canonical_digest

from .cohort import CohortMeasurement
from .sources import SourceReconciliation

QUALIFICATION_SCHEMA = "fdai.governance-qualification-record.v1"
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class Readiness(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class QualificationBinding:
    """The exact installation facts recorded before collection."""

    installation_id: str
    management_scope_id: str
    environment_class: str
    rule_generation_digest: str
    ontology_release_digest: str
    provider_revisions: Mapping[str, str]
    evidence_cutoff: datetime

    def __post_init__(self) -> None:
        if not (self.installation_id and self.management_scope_id and self.environment_class):
            raise ValueError("qualification binding MUST name installation, scope, and class")
        for digest in (self.rule_generation_digest, self.ontology_release_digest):
            if _DIGEST.fullmatch(digest) is None:
                raise ValueError("qualification binding revisions MUST be sha256 digests")
        if not self.provider_revisions or any(
            not name or not revision for name, revision in self.provider_revisions.items()
        ):
            raise ValueError("qualification binding MUST pin every provider revision")
        if self.evidence_cutoff.tzinfo is None:
            raise ValueError("evidence cutoff MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class QualificationRecord:
    binding: QualificationBinding
    readiness: Readiness
    blocking_reasons: tuple[str, ...]
    sources_digest: str
    measurement_digest: str | None
    record_digest: str
    authority: str = "none"


def build_qualification_record(
    binding: QualificationBinding,
    sources: SourceReconciliation,
    measurement: CohortMeasurement | None,
) -> QualificationRecord:
    """Build the review-only record; every missing or held input is a named blocker."""

    reasons: list[str] = []
    if sources.evidence_cutoff != binding.evidence_cutoff:
        reasons.append("source_cutoff_differs_from_binding")
    reasons.extend(f"source_hold:{hold.source_id}:{hold.reason.value}" for hold in sources.holds)
    if measurement is None:
        reasons.append("cohort_not_measured")
    else:
        if measurement.false_positive_rate is None:
            reasons.append("false_positive_denominator_empty")
        if measurement.false_negative_rate is None:
            reasons.append("false_negative_denominator_empty")
        if measurement.held_violation or measurement.held_compliant:
            reasons.append("cohort_has_holds")
    blocking = tuple(sorted(dict.fromkeys(reasons)))
    readiness = Readiness.BLOCKED if blocking else Readiness.READY_FOR_REVIEW
    measurement_digest = measurement.digest if measurement is not None else None
    material = {
        "schema_version": QUALIFICATION_SCHEMA,
        "installation_id": binding.installation_id,
        "management_scope_id": binding.management_scope_id,
        "environment_class": binding.environment_class,
        "rule_generation_digest": binding.rule_generation_digest,
        "ontology_release_digest": binding.ontology_release_digest,
        "provider_revisions": dict(sorted(binding.provider_revisions.items())),
        "evidence_cutoff": binding.evidence_cutoff.isoformat(),
        "readiness": readiness.value,
        "blocking_reasons": list(blocking),
        "sources_digest": sources.digest,
        "measurement_digest": measurement_digest,
        "authority": "none",
    }
    return QualificationRecord(
        binding=binding,
        readiness=readiness,
        blocking_reasons=blocking,
        sources_digest=sources.digest,
        measurement_digest=measurement_digest,
        record_digest=canonical_digest(material),
    )


def reconcile_ledger_digests(
    record: QualificationRecord, ledger_digests: Collection[str]
) -> tuple[str, ...]:
    """Return the evidence digests the ledger fails to cite; an empty tuple means reconciled."""

    required = {record.record_digest, record.sources_digest}
    if record.measurement_digest is not None:
        required.add(record.measurement_digest)
    return tuple(sorted(required - set(ledger_digests)))
