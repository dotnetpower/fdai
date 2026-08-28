"""Replay-stable coverage accounting for governed operational claims."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.ontology_query import content_digest

_MAX_EVIDENCE_DIGESTS = 64
_MAX_DISPOSITIONS = 8


class OperationalCoverageDomain(StrEnum):
    """Governed universes that require independent coverage accounting."""

    ASSET_INVENTORY = "asset_inventory"
    GOVERNANCE_EVALUATION = "governance_evaluation"
    OPERATING_SCOPE = "operating_scope"
    INCIDENT_DIAGNOSIS = "incident_diagnosis"
    REMEDIATION_EFFECT = "remediation_effect"
    KNOWLEDGE_GROUNDING = "knowledge_grounding"


class OperationalCoverageDisposition(StrEnum):
    """Why one denominator item is or is not covered."""

    COVERED = "covered"
    UNKNOWN = "unknown"
    STALE = "stale"
    UNSUPPORTED = "unsupported"
    INACCESSIBLE = "inaccessible"
    CONFLICTING = "conflicting"
    INVALID = "invalid"


class OperationalCoverageCount(ContractBase):
    """Count denominator items with one terminal coverage disposition."""

    disposition: OperationalCoverageDisposition
    count: Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]


class _OperationalCoverageReceiptBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    domain: OperationalCoverageDomain
    scope_digest: Digest
    denominator_digest: Digest
    denominator_count: Annotated[int, Field(strict=True, ge=1, le=1_000_000_000)]
    disposition_counts: Annotated[
        tuple[OperationalCoverageCount, ...],
        Field(min_length=1, max_length=_MAX_DISPOSITIONS),
    ]
    evidence_digests: Annotated[
        tuple[Digest, ...],
        Field(min_length=1, max_length=_MAX_EVIDENCE_DIGESTS),
    ]
    evidence_cutoff: datetime
    evaluated_at: datetime
    fresh_until: datetime
    target_basis_points: Annotated[int, Field(strict=True, ge=0, le=10_000)] = 9_900
    zero_tolerance_dispositions: tuple[OperationalCoverageDisposition, ...] = (
        OperationalCoverageDisposition.CONFLICTING,
        OperationalCoverageDisposition.INVALID,
    )
    coverage_basis_points: Annotated[int, Field(strict=True, ge=0, le=10_000)]
    accounting_complete: bool
    target_met: bool
    execution_authority: Literal[False] = False


class OperationalCoverageReceipt(_OperationalCoverageReceiptBody):
    """Account for one immutable operational universe without granting authority."""

    receipt_digest: Digest

    @model_validator(mode="after")
    def _coverage_is_canonical(self) -> OperationalCoverageReceipt:
        dispositions = tuple(item.disposition for item in self.disposition_counts)
        if dispositions != tuple(sorted(dispositions, key=str)):
            raise ValueError("coverage dispositions MUST be unique and ordered")
        if len(dispositions) != len(set(dispositions)):
            raise ValueError("coverage dispositions MUST be unique and ordered")
        if self.evidence_digests != tuple(sorted(self.evidence_digests)):
            raise ValueError("coverage evidence digests MUST be unique and ordered")
        if len(self.evidence_digests) != len(set(self.evidence_digests)):
            raise ValueError("coverage evidence digests MUST be unique and ordered")
        if self.zero_tolerance_dispositions != tuple(
            sorted(self.zero_tolerance_dispositions, key=str)
        ):
            raise ValueError("zero-tolerance dispositions MUST be unique and ordered")
        if len(self.zero_tolerance_dispositions) != len(set(self.zero_tolerance_dispositions)):
            raise ValueError("zero-tolerance dispositions MUST be unique and ordered")
        for field_name, value in (
            ("evidence_cutoff", self.evidence_cutoff),
            ("evaluated_at", self.evaluated_at),
            ("fresh_until", self.fresh_until),
        ):
            if value.tzinfo is None:
                raise ValueError(f"coverage {field_name} MUST include a timezone")
        if self.evidence_cutoff > self.evaluated_at:
            raise ValueError("coverage evidence cutoff MUST NOT be in the future")
        if self.fresh_until < self.evidence_cutoff:
            raise ValueError("coverage freshness MUST NOT end before the evidence cutoff")

        counts = {item.disposition: item.count for item in self.disposition_counts}
        accounted_count = sum(counts.values())
        if accounted_count > self.denominator_count:
            raise ValueError("coverage disposition counts MUST NOT exceed the denominator")
        expected_complete = accounted_count == self.denominator_count
        if self.accounting_complete != expected_complete:
            raise ValueError("coverage accounting completeness does not match counts")

        covered_count = counts.get(OperationalCoverageDisposition.COVERED, 0)
        expected_basis_points = covered_count * 10_000 // self.denominator_count
        if self.coverage_basis_points != expected_basis_points:
            raise ValueError("coverage basis points do not match counts")

        zero_tolerance_clear = all(
            counts.get(disposition, 0) == 0 for disposition in self.zero_tolerance_dispositions
        )
        expected_target_met = (
            expected_complete
            and self.evaluated_at <= self.fresh_until
            and expected_basis_points >= self.target_basis_points
            and zero_tolerance_clear
        )
        if self.target_met != expected_target_met:
            raise ValueError("coverage target result does not match the governed inputs")

        expected_digest = content_digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected_digest:
            raise ValueError("coverage receipt digest does not match its content")
        return self


def operational_coverage_receipt_digest(**values: object) -> str:
    """Return the canonical digest for an operational coverage receipt body."""

    body = dict(values)
    body.pop("receipt_digest", None)
    candidate = _OperationalCoverageReceiptBody.model_validate(body)
    return content_digest(candidate.model_dump(mode="json"))


__all__ = [
    "OperationalCoverageCount",
    "OperationalCoverageDisposition",
    "OperationalCoverageDomain",
    "OperationalCoverageReceipt",
    "operational_coverage_receipt_digest",
]
