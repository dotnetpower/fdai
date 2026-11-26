"""Authority-free scoped Rule coverage records for one framework workload assessment.

A record projects Forseti's complete version 2 baseline coverage onto one exact workload scope.
It is a read model: it cannot change Rule activation, approval, risk, promotion, remediation, or
execution authority. Validation recomputes every digest, so a record that mixes scope,
activation, catalog, or inventory identities is rejected instead of reinterpreted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from pydantic import Field, model_validator

from fdai_service_contracts.baseline_evaluation import BaselineEvaluationCoverage
from fdai_service_contracts.executor_models import ContractBase, Digest

FRAMEWORK_RULE_COVERAGE_RECORD_PREFIX = "framework-rule-coverage:record:"
FRAMEWORK_RULE_COVERAGE_LATEST_KEY = "framework-rule-coverage:latest"

Ref = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.:-]{0,159}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=10_000_000)]
BoundedText = Annotated[str, Field(strict=True, min_length=1, max_length=2048)]
RuleId = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


def _canonical_digest(value: object) -> str:
    # Same canonical JSON as content_digest, without its 64 KiB bound: a workload record with
    # hundreds of resources is legitimately larger, and its size is bounded by the field limits.
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ScopedRuleCoverageIdentityError(ValueError):
    """A scoped coverage record does not belong to the expected baseline, scope, or pin."""


class ScopedRuleCoverageResource(ContractBase):
    """One workload resource mapped from its provider id to its inventory reference."""

    provider_resource_id: BoundedText
    resource_ref: Ref
    resource_type: BoundedText


class ScopedRuleCoverageRule(ContractBase):
    """Terminal outcome accounting for one activated or requested Rule in the workload."""

    rule_id: RuleId
    member_rule_digest: Digest | None
    evaluated_rule_digest: Digest | None
    eligible_set_digest: Digest
    eligible_count: Count
    compliant_count: Count
    violated_count: Count
    abstained_count: Count
    missing_count: Count
    duplicate_count: Count
    conflicting_count: Count
    unexpected_count: Count
    revision_mismatch_count: Count

    @property
    def covered_count(self) -> int:
        return self.compliant_count + self.violated_count + self.abstained_count

    @model_validator(mode="after")
    def _accounted(self) -> ScopedRuleCoverageRule:
        accounted = (
            self.covered_count + self.missing_count + self.duplicate_count + self.conflicting_count
        )
        if accounted != self.eligible_count:
            raise ValueError("scoped Rule coverage MUST account every eligible pair exactly once")
        if self.revision_mismatch_count > self.covered_count:
            raise ValueError("scoped Rule coverage revision mismatches exceed covered pairs")
        return self


class ScopedRuleCoverageRecord(ContractBase):
    """Versioned scoped coverage for one workload, activation, and inventory generation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    framework_id: Ref
    workload_id: BoundedText
    scope_digest: Digest
    resource_set_digest: Digest
    resources: Annotated[tuple[ScopedRuleCoverageResource, ...], Field(max_length=10_000)]
    rule_activation_generation_id: Annotated[str, Field(pattern=r"^rule-activation-[a-f0-9]{32}$")]
    rule_activation_generation_digest: Digest
    rule_catalog_digest: Digest
    evaluated_rule_catalog_digest: Digest
    dispatch_signal: Ref
    expected_pair_set_digest: Digest
    inventory_generation: BoundedText
    baseline_generation_id: Ref
    inventory_observation_digest: Digest
    inventory_observed_at: datetime
    recorded_at: datetime
    rules: Annotated[tuple[ScopedRuleCoverageRule, ...], Field(max_length=100_000)]
    unattributed_unexpected_count: Count
    scoped_coverage_digest: Digest
    baseline_coverage_digest: Digest
    baseline_audit_ref: Ref
    baseline_audit_digest: Digest
    audit_ref: Ref
    audit_digest: Digest
    projection_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    record_digest: Digest

    def rule(self, rule_id: str) -> ScopedRuleCoverageRule | None:
        return next((item for item in self.rules if item.rule_id == rule_id), None)

    @model_validator(mode="after")
    def _canonical_record(self) -> ScopedRuleCoverageRecord:
        for label, value in (
            ("inventory_observed_at", self.inventory_observed_at),
            ("recorded_at", self.recorded_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"scoped Rule coverage {label} MUST be timezone-aware")
        if self.recorded_at < self.inventory_observed_at:
            raise ValueError("scoped Rule coverage recorded_at MUST follow the observation")
        rule_ids = [item.rule_id for item in self.rules]
        if rule_ids != sorted(set(rule_ids)):
            raise ValueError("scoped Rule coverage rules MUST be unique and ordered")
        provider_ids = [item.provider_resource_id for item in self.resources]
        if provider_ids != sorted(set(provider_ids)):
            raise ValueError("scoped Rule coverage resources MUST be unique and ordered")
        if len({item.resource_ref for item in self.resources}) != len(self.resources):
            # One inventory reference for two provider ids would merge their outcomes.
            raise ValueError("scoped Rule coverage resource references MUST be unique")
        if self.resource_set_digest != scoped_rule_coverage_resource_set_digest(self.resources):
            raise ValueError("scoped Rule coverage resource set digest mismatch")
        if self.scoped_coverage_digest != scoped_rule_coverage_digest(self):
            raise ValueError("scoped Rule coverage digest mismatch")
        expected = framework_rule_coverage_record_digest(
            **self.model_dump(mode="python", exclude={"record_digest"})
        )
        if self.record_digest != expected:
            raise ValueError("scoped Rule coverage record digest mismatch")
        return self


def scoped_rule_coverage_resource_set_digest(
    resources: tuple[ScopedRuleCoverageResource, ...],
) -> str:
    """Return the digest of the ordered provider-id to inventory-reference mapping."""

    return _canonical_digest([item.model_dump(mode="json") for item in resources])


def scoped_rule_coverage_digest(record: ScopedRuleCoverageRecord) -> str:
    """Recompute the scoped coverage digest the ``t0-rule-evaluator`` receipts carry.

    The material matches the Core scoped coverage projection field for field, so a receipt's
    ``coverage_digest`` identifies exactly one persisted record.
    """

    return _canonical_digest(
        {
            "scope_digest": record.scope_digest,
            "inventory_generation": record.inventory_generation,
            "inventory_observed_at": record.inventory_observed_at.isoformat(),
            "recorded_at": record.recorded_at.isoformat(),
            "activation": {
                "generation_id": record.rule_activation_generation_id,
                "generation_digest": record.rule_activation_generation_digest,
                "rule_catalog_digest": record.rule_catalog_digest,
            },
            "dispatch_signal": record.dispatch_signal,
            "rules": [item.model_dump(mode="json") for item in record.rules],
            "unattributed_unexpected_count": record.unattributed_unexpected_count,
        }
    )


def framework_rule_coverage_record_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by a scoped coverage record."""

    body = dict(values)
    body.pop("record_digest", None)
    # Nested items may arrive as mappings from a stored record; serialize them as models.
    body["resources"] = tuple(
        ScopedRuleCoverageResource.model_validate(item) for item in _items(body, "resources")
    )
    body["rules"] = tuple(
        ScopedRuleCoverageRule.model_validate(item) for item in _items(body, "rules")
    )
    candidate = ScopedRuleCoverageRecord.model_construct(
        record_digest="",
        **cast(dict[str, Any], body),
    )
    return _canonical_digest(candidate.model_dump(mode="json", exclude={"record_digest"}))


def _items(body: dict[str, object], field: str) -> tuple[object, ...]:
    value = body.get(field, ())
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"scoped Rule coverage {field} MUST be a sequence")
    return tuple(value)


def framework_rule_coverage_record_key(record_digest: str) -> str:
    """Return the immutable state key for one scoped coverage record."""

    return FRAMEWORK_RULE_COVERAGE_RECORD_PREFIX + record_digest.removeprefix("sha256:")


def verify_scoped_rule_coverage_identity(
    record: ScopedRuleCoverageRecord,
    *,
    baseline: BaselineEvaluationCoverage,
    scope_digest: str | None = None,
    rule_activation_generation_digest: str | None = None,
) -> None:
    """Reject a record whose identities differ from its baseline, scope, or activation pin.

    Raises:
        ScopedRuleCoverageIdentityError: naming the first mismatched identity.
    """

    checks: tuple[tuple[str, object, object], ...] = (
        ("baseline coverage", record.baseline_coverage_digest, baseline.coverage_digest),
        ("baseline audit", record.baseline_audit_ref, baseline.audit_ref),
        ("baseline audit digest", record.baseline_audit_digest, baseline.audit_digest),
        ("inventory generation", record.baseline_generation_id, baseline.generation_id),
        (
            "inventory observation",
            record.inventory_observation_digest,
            baseline.inventory_observation_digest,
        ),
        (
            "activation generation",
            record.rule_activation_generation_id,
            baseline.rule_activation_generation_id,
        ),
        (
            "activation digest",
            record.rule_activation_generation_digest,
            baseline.rule_activation_generation_digest,
        ),
        ("Rule catalog", record.rule_catalog_digest, baseline.rule_catalog_digest),
        (
            "evaluated Rule catalog",
            record.evaluated_rule_catalog_digest,
            baseline.evaluated_rule_catalog_digest,
        ),
        ("dispatch signal", record.dispatch_signal, baseline.dispatch_signal),
        ("expected pair set", record.expected_pair_set_digest, baseline.expected_pair_set_digest),
    )
    for label, actual, expected in checks:
        if actual != expected:
            raise ScopedRuleCoverageIdentityError(f"scoped Rule coverage {label} mismatch")
    if not baseline.complete:
        raise ScopedRuleCoverageIdentityError("scoped Rule coverage requires a complete baseline")
    if scope_digest is not None and record.scope_digest != scope_digest:
        raise ScopedRuleCoverageIdentityError("scoped Rule coverage scope mismatch")
    if (
        rule_activation_generation_digest is not None
        and record.rule_activation_generation_digest != rule_activation_generation_digest
    ):
        raise ScopedRuleCoverageIdentityError("scoped Rule coverage activation pin mismatch")


__all__ = [
    "FRAMEWORK_RULE_COVERAGE_LATEST_KEY",
    "FRAMEWORK_RULE_COVERAGE_RECORD_PREFIX",
    "ScopedRuleCoverageIdentityError",
    "ScopedRuleCoverageRecord",
    "ScopedRuleCoverageResource",
    "ScopedRuleCoverageRule",
    "framework_rule_coverage_record_digest",
    "framework_rule_coverage_record_key",
    "scoped_rule_coverage_digest",
    "scoped_rule_coverage_resource_set_digest",
    "verify_scoped_rule_coverage_identity",
]
