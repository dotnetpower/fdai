"""Authority-free terminal records for complete inventory baseline evaluation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import Field, model_validator

from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.ontology_query import content_digest

Ref = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.:-]{0,159}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=10_000_000)]


class BaselineEvaluationTerminalOutcome(StrEnum):
    """Terminal states Forseti can assign to one Resource and Rule pair."""

    COMPLIANT = "compliant"
    VIOLATED = "violated"
    ABSTAINED = "abstained"


class BaselineEvaluationOutcome(ContractBase):
    """One per-Rule terminal result for one Resource in a complete inventory generation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    generation_id: Ref
    generation_digest: Digest
    inventory_observation_digest: Digest
    resource_ref: Ref
    resource_digest: Digest
    catalog_revision: Digest
    rule_ref: Ref
    rule_revision: Digest
    expected_denominator: Annotated[int, Field(strict=True, ge=1, le=10_000_000)]
    outcome: BaselineEvaluationTerminalOutcome
    reason_code: Ref | None = None
    evaluation_receipt_ref: Ref
    evaluation_receipt_digest: Digest
    saga_audit_ref: Ref
    saga_audit_digest: Digest
    evaluated_at: datetime
    execution_authority: Literal[False] = False
    outcome_digest: Digest

    @model_validator(mode="after")
    def _canonical_outcome(self) -> BaselineEvaluationOutcome:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("baseline evaluation outcome evaluated_at MUST be timezone-aware")
        if self.outcome is BaselineEvaluationTerminalOutcome.ABSTAINED:
            if self.reason_code is None:
                raise ValueError("abstained baseline evaluation outcome MUST include a reason")
        elif self.reason_code is not None:
            raise ValueError("non-abstained baseline evaluation outcome MUST NOT include a reason")
        expected = baseline_evaluation_outcome_digest(
            generation_id=self.generation_id,
            generation_digest=self.generation_digest,
            inventory_observation_digest=self.inventory_observation_digest,
            resource_ref=self.resource_ref,
            resource_digest=self.resource_digest,
            catalog_revision=self.catalog_revision,
            rule_ref=self.rule_ref,
            rule_revision=self.rule_revision,
            expected_denominator=self.expected_denominator,
            outcome=self.outcome,
            reason_code=self.reason_code,
            evaluation_receipt_ref=self.evaluation_receipt_ref,
            evaluation_receipt_digest=self.evaluation_receipt_digest,
            saga_audit_ref=self.saga_audit_ref,
            saga_audit_digest=self.saga_audit_digest,
            evaluated_at=self.evaluated_at,
            execution_authority=self.execution_authority,
        )
        if self.outcome_digest != expected:
            raise ValueError("baseline evaluation outcome digest mismatch")
        return self


class BaselineEvaluationCompletion(ContractBase):
    """Completion record proving the current generation/catalog denominator is covered."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    generation_id: Ref
    generation_digest: Digest
    inventory_observation_digest: Digest
    catalog_revision: Digest
    expected_denominator: Count
    compliant_count: Count
    violated_count: Count
    abstained_count: Count
    outcome_set_digest: Digest
    completion_receipt_ref: Ref
    completion_receipt_digest: Digest
    saga_audit_ref: Ref
    saga_audit_digest: Digest
    completed_at: datetime
    complete: Literal[True] = True
    projection_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_digest: Digest

    @model_validator(mode="after")
    def _canonical_completion(self) -> BaselineEvaluationCompletion:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("baseline evaluation completion completed_at MUST be timezone-aware")
        observed = self.compliant_count + self.violated_count + self.abstained_count
        if observed != self.expected_denominator:
            raise ValueError("baseline evaluation completion counts MUST match the denominator")
        expected = baseline_evaluation_completion_digest(
            generation_id=self.generation_id,
            generation_digest=self.generation_digest,
            inventory_observation_digest=self.inventory_observation_digest,
            catalog_revision=self.catalog_revision,
            expected_denominator=self.expected_denominator,
            compliant_count=self.compliant_count,
            violated_count=self.violated_count,
            abstained_count=self.abstained_count,
            outcome_set_digest=self.outcome_set_digest,
            completion_receipt_ref=self.completion_receipt_ref,
            completion_receipt_digest=self.completion_receipt_digest,
            saga_audit_ref=self.saga_audit_ref,
            saga_audit_digest=self.saga_audit_digest,
            completed_at=self.completed_at,
            complete=self.complete,
            projection_authority=self.projection_authority,
            execution_authority=self.execution_authority,
        )
        if self.completion_digest != expected:
            raise ValueError("baseline evaluation completion digest mismatch")
        return self


def baseline_evaluation_outcome_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by an outcome record."""

    body = dict(values)
    body.pop("outcome_digest", None)
    candidate = BaselineEvaluationOutcome.model_construct(
        outcome_digest="",
        **cast(dict[str, Any], body),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"outcome_digest"}))


def baseline_evaluation_completion_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by a completion record."""

    body = dict(values)
    body.pop("completion_digest", None)
    candidate = BaselineEvaluationCompletion.model_construct(
        completion_digest="",
        **cast(dict[str, Any], body),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"completion_digest"}))


__all__ = [
    "BaselineEvaluationCompletion",
    "BaselineEvaluationOutcome",
    "BaselineEvaluationTerminalOutcome",
    "baseline_evaluation_completion_digest",
    "baseline_evaluation_outcome_digest",
]
