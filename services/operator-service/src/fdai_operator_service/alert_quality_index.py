"""Pure predecessor and generation rules for immutable alert-quality indexes."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from fdai_service_contracts.alert_noise import NoiseAssessment, digest_record
from fdai_service_contracts.executor_models import ContractBase, Digest
from pydantic import AwareDatetime, Field, model_validator

from fdai_operator_service.alert_quality_records import (
    ALERT_QUALITY_PREFIX,
    MAX_ALERT_QUALITY_PLANS,
    AlertQualityUnavailableError,
)


class _Index(ContractBase):
    """One immutable generation binding its report, plans and predecessor."""

    kind: Literal["operator.alert-quality.index"] = "operator.alert-quality.index"
    binding_digest: Digest
    revision: Annotated[int, Field(strict=True, ge=1, le=9_223_372_036_854_775_807)]
    previous_digest: Digest | None
    evidence_digest: Digest
    assessment_digest: Digest
    observed_at: AwareDatetime
    plan_digests: Annotated[tuple[Digest, ...], Field(max_length=MAX_ALERT_QUALITY_PLANS)] = ()

    @model_validator(mode="after")
    def chain(self) -> Self:
        if (self.revision == 1) != (self.previous_digest is None):
            raise ValueError("alert quality index predecessor is invalid")
        if self.plan_digests != tuple(sorted(set(self.plan_digests))):
            raise ValueError("alert quality index plans MUST be sorted and unique")
        return self


def _index_key(binding: str, revision: int) -> str:
    return f"{ALERT_QUALITY_PREFIX}{binding[7:]}:index:{revision:020d}"


def _verify_successor(previous: _Index, current: _Index) -> None:
    """Reject changed bindings, non-successors, report drift and non-advancing plans."""
    same_evidence = current.evidence_digest == previous.evidence_digest
    if (
        current.binding_digest != previous.binding_digest
        or current.revision != previous.revision + 1
        or current.previous_digest != digest_record(previous)
        or (
            same_evidence
            and (
                current.assessment_digest != previous.assessment_digest
                or current.observed_at != previous.observed_at
                or not set(previous.plan_digests) < set(current.plan_digests)
            )
        )
        or (
            not same_evidence
            and (current.observed_at <= previous.observed_at or current.plan_digests)
        )
    ):
        raise AlertQualityUnavailableError("alert quality index chain is invalid")


def _next_index(
    head: _Index | None,
    *,
    binding: str,
    assessment: NoiseAssessment,
    plan_digests: tuple[str, ...],
) -> _Index:
    return _Index(
        binding_digest=binding,
        revision=1 if head is None else head.revision + 1,
        previous_digest=None if head is None else digest_record(head),
        evidence_digest=assessment.evidence_digest,
        assessment_digest=digest_record(assessment),
        observed_at=assessment.observed_at,
        plan_digests=plan_digests,
    )
