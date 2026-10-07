"""Scoped coverage of activated Rule outcomes for one framework workload.

The expected Resource and Rule pairs come from the same ``RuleIndex`` dispatch T0
uses, never from the outcomes that were written. Coverage is therefore complete
only when every expected pair has exactly one terminal outcome and no scoped
outcome lacks an expected pair. Nothing here grants activation, approval, or
execution authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai_service_contracts.baseline_evaluation import (
    BaselineEvaluationOutcome,
    BaselineEvaluationTerminalOutcome,
)
from fdai_service_contracts.rule_activation import RuleActivationGeneration

from fdai.core.framework_assessment import FrameworkRuleActivationPin
from fdai.core.rule_activation.generation import rule_digest
from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.rule_catalog.schema.framework_assessment import canonical_digest

T0_RULE_EVALUATOR = "t0-rule-evaluator"
INVENTORY_OBSERVATION_SIGNAL = "inventory.resource_observed"

_BARE_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_PREFIXED_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")


class RuleEvidenceLimitation(StrEnum):
    """Bounded codes explaining why a Rule requirement stays unknown."""

    SCOPE_MISMATCH = "scope_mismatch"
    RULE_NOT_ACTIVATED = "rule_not_activated"
    ACTIVATION_CATALOG_DRIFT = "activation_catalog_drift"
    RULE_REVISION_DRIFT = "rule_revision_drift"
    STALE_INVENTORY = "stale_inventory"
    PAIR_MISSING = "pair_missing"
    DUPLICATE_PAIR = "duplicate_pair"
    CONFLICTING_PAIR = "conflicting_pair"
    UNEXPECTED_PAIR = "unexpected_pair"
    NO_ELIGIBLE_RESOURCE = "no_eligible_resource"
    HELD_FOR_REVIEW = "held_for_review"


def canonical_sha256(value: str) -> str:
    """Normalize a bare or ``sha256:``-prefixed lowercase SHA-256 digest."""

    if _PREFIXED_SHA256.fullmatch(value) is not None:
        return value
    if _BARE_SHA256.fullmatch(value) is not None:
        return f"sha256:{value}"
    raise ValueError("digest MUST be lowercase SHA-256")


def activation_pin(generation: RuleActivationGeneration) -> FrameworkRuleActivationPin:
    """Return the assessment pin for one installed Rule activation generation."""

    return FrameworkRuleActivationPin(
        generation_id=generation.generation_id,
        generation_digest=canonical_sha256(generation.generation_digest),
        rule_catalog_digest=canonical_sha256(generation.catalog_digest),
    )


def baseline_ref(prefix: str, value: str) -> str:
    """Return the bounded reference Forseti records in baseline evaluation outcomes."""

    candidate = f"{prefix}:{value}"
    normalized = candidate.replace(":", "").replace(".", "").replace("-", "").replace("_", "")
    if len(candidate) <= 160 and normalized.isalnum() and candidate[0].islower():
        return candidate
    return f"{prefix}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]}"


@dataclass(frozen=True, slots=True)
class WorkloadRuleResource:
    """One workload resource in neutral inventory identity."""

    resource_id: str
    resource_type: str

    def __post_init__(self) -> None:
        if not self.resource_id.strip() or not self.resource_type.strip():
            raise ValueError("workload Rule resource requires an id and a type")


@dataclass(frozen=True, slots=True)
class ExpectedRulePair:
    """One Resource and Rule pair that T0 dispatch selects for evaluation."""

    resource_id: str
    rule_id: str
    evaluated_rule_digest: str


@dataclass(frozen=True, slots=True)
class RuleCoverage:
    """Terminal outcome accounting for one activated or requested Rule."""

    rule_id: str
    member_rule_digest: str | None
    evaluated_rule_digest: str | None
    eligible_set_digest: str
    eligible_count: int
    compliant_count: int
    violated_count: int
    abstained_count: int
    missing_count: int
    duplicate_count: int
    conflicting_count: int
    unexpected_count: int
    revision_mismatch_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "member_rule_digest": self.member_rule_digest,
            "evaluated_rule_digest": self.evaluated_rule_digest,
            "eligible_set_digest": self.eligible_set_digest,
            "eligible_count": self.eligible_count,
            "compliant_count": self.compliant_count,
            "violated_count": self.violated_count,
            "abstained_count": self.abstained_count,
            "missing_count": self.missing_count,
            "duplicate_count": self.duplicate_count,
            "conflicting_count": self.conflicting_count,
            "unexpected_count": self.unexpected_count,
            "revision_mismatch_count": self.revision_mismatch_count,
        }


@dataclass(frozen=True, slots=True)
class ScopedRuleCoverage:
    """Content-addressed coverage of activated Rules for one exact workload scope."""

    scope_digest: str
    inventory_generation: str
    inventory_observed_at: datetime
    recorded_at: datetime
    activation: FrameworkRuleActivationPin
    dispatch_signal: str
    rules: tuple[RuleCoverage, ...]
    unattributed_unexpected_count: int
    coverage_digest: str

    def rule(self, rule_id: str) -> RuleCoverage | None:
        return next((item for item in self.rules if item.rule_id == rule_id), None)


def expected_rule_pairs(
    *,
    resources: Sequence[WorkloadRuleResource],
    index: RuleIndex,
    signal_type: str = INVENTORY_OBSERVATION_SIGNAL,
) -> tuple[ExpectedRulePair, ...]:
    """Select expected pairs with exactly the dispatch T0 applies to inventory observations.

    ``submission_criteria`` are catalog admission checks and never filter pairs here.
    """

    resource_ids = [item.resource_id for item in resources]
    if len(resource_ids) != len(set(resource_ids)):
        raise ValueError("workload Rule resources MUST have unique resource ids")
    pairs = [
        ExpectedRulePair(
            resource_id=resource.resource_id,
            rule_id=rule.id,
            evaluated_rule_digest=canonical_sha256(rule_digest(rule)),
        )
        for resource in resources
        for rule in index.rules_for_signal(
            resource_type=resource.resource_type,
            signal_type=signal_type,
        )
    ]
    return tuple(sorted(pairs, key=lambda pair: (pair.rule_id, pair.resource_id)))


def build_scoped_coverage(
    *,
    scope_digest: str,
    resources: Sequence[WorkloadRuleResource],
    expected_pairs: Sequence[ExpectedRulePair],
    outcomes: Iterable[BaselineEvaluationOutcome],
    activation: RuleActivationGeneration,
    requested_rule_ids: Iterable[str],
    inventory_generation: str,
    inventory_observed_at: datetime,
    recorded_at: datetime,
    dispatch_signal: str = INVENTORY_OBSERVATION_SIGNAL,
) -> ScopedRuleCoverage:
    """Account every expected pair against the baseline outcomes for one workload.

    Outcomes for resources outside the workload are ignored. Outcomes from a different
    inventory generation are rejected rather than reinterpreted.
    """

    if _PREFIXED_SHA256.fullmatch(scope_digest) is None:
        raise ValueError("scoped Rule coverage scope_digest MUST be lowercase SHA-256")
    if inventory_observed_at.tzinfo is None or recorded_at.tzinfo is None:
        raise ValueError("scoped Rule coverage timestamps MUST be timezone-aware")
    if recorded_at < inventory_observed_at:
        raise ValueError("scoped Rule coverage recorded_at MUST follow the observation")
    generation_ref = baseline_ref("generation", inventory_generation)
    workload_refs = {baseline_ref("resource", item.resource_id) for item in resources}
    members = {
        member.rule_id: canonical_sha256(member.rule_digest) for member in activation.members
    }
    rule_ref_to_id = {baseline_ref("rule", rule_id): rule_id for rule_id in members}
    for pair in expected_pairs:
        if pair.rule_id not in members:
            raise ValueError("expected Rule pairs MUST come from activation members")
        if baseline_ref("resource", pair.resource_id) not in workload_refs:
            raise ValueError("expected Rule pairs MUST stay inside the workload scope")

    scoped: dict[tuple[str, str], list[BaselineEvaluationOutcome]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.generation_id != generation_ref:
            raise ValueError("baseline outcomes MUST belong to the pinned inventory generation")
        if outcome.resource_ref in workload_refs:
            scoped[(outcome.resource_ref, outcome.rule_ref)].append(outcome)

    expected_by_rule: dict[str, list[ExpectedRulePair]] = defaultdict(list)
    for pair in expected_pairs:
        expected_by_rule[pair.rule_id].append(pair)
    expected_keys = {
        (baseline_ref("resource", pair.resource_id), baseline_ref("rule", pair.rule_id))
        for pair in expected_pairs
    }

    unexpected_by_rule: dict[str, int] = defaultdict(int)
    unattributed = 0
    for key, records in scoped.items():
        if key in expected_keys:
            continue
        rule_id = rule_ref_to_id.get(key[1])
        if rule_id is None:
            unattributed += len(records)
        else:
            unexpected_by_rule[rule_id] += len(records)

    # Every member is accounted for, so absence from coverage really means not activated.
    rule_ids = sorted(set(requested_rule_ids) | set(members) | set(expected_by_rule))
    coverages = tuple(
        _rule_coverage(
            rule_id=rule_id,
            member_rule_digest=members.get(rule_id),
            pairs=expected_by_rule.get(rule_id, []),
            scoped=scoped,
            unexpected_count=unexpected_by_rule.get(rule_id, 0),
        )
        for rule_id in rule_ids
    )
    pin = activation_pin(activation)
    material = {
        "scope_digest": scope_digest,
        "inventory_generation": inventory_generation,
        "inventory_observed_at": inventory_observed_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "activation": pin.to_dict(),
        "dispatch_signal": dispatch_signal,
        "rules": [item.to_dict() for item in coverages],
        "unattributed_unexpected_count": unattributed,
    }
    return ScopedRuleCoverage(
        scope_digest=scope_digest,
        inventory_generation=inventory_generation,
        inventory_observed_at=inventory_observed_at,
        recorded_at=recorded_at,
        activation=pin,
        dispatch_signal=dispatch_signal,
        rules=coverages,
        unattributed_unexpected_count=unattributed,
        coverage_digest=canonical_digest(material),
    )


def _rule_coverage(
    *,
    rule_id: str,
    member_rule_digest: str | None,
    pairs: Sequence[ExpectedRulePair],
    scoped: Mapping[tuple[str, str], list[BaselineEvaluationOutcome]],
    unexpected_count: int,
) -> RuleCoverage:
    counts = dict.fromkeys(
        ("compliant", "violated", "abstained", "missing", "duplicate", "conflicting", "revision"),
        0,
    )
    for pair in pairs:
        records = scoped.get(
            (baseline_ref("resource", pair.resource_id), baseline_ref("rule", pair.rule_id)),
            [],
        )
        if not records:
            counts["missing"] += 1
            continue
        if len({record.outcome for record in records}) > 1:
            counts["conflicting"] += 1
            continue
        if len(records) > 1:
            counts["duplicate"] += 1
            continue
        record = records[0]
        if member_rule_digest is not None and record.rule_revision != member_rule_digest:
            counts["revision"] += 1
        if record.outcome is BaselineEvaluationTerminalOutcome.COMPLIANT:
            counts["compliant"] += 1
        elif record.outcome is BaselineEvaluationTerminalOutcome.VIOLATED:
            counts["violated"] += 1
        else:
            counts["abstained"] += 1
    evaluated_digests = {pair.evaluated_rule_digest for pair in pairs}
    return RuleCoverage(
        rule_id=rule_id,
        member_rule_digest=member_rule_digest,
        evaluated_rule_digest=(
            next(iter(evaluated_digests)) if len(evaluated_digests) == 1 else None
        ),
        eligible_set_digest=_eligible_set_digest(rule_id, pairs),
        eligible_count=len(pairs),
        compliant_count=counts["compliant"],
        violated_count=counts["violated"],
        abstained_count=counts["abstained"],
        missing_count=counts["missing"],
        duplicate_count=counts["duplicate"],
        conflicting_count=counts["conflicting"],
        unexpected_count=unexpected_count,
        revision_mismatch_count=counts["revision"],
    )


def _eligible_set_digest(rule_id: str, pairs: Sequence[ExpectedRulePair]) -> str:
    encoded = json.dumps(
        {"rule_id": rule_id, "resource_ids": sorted(pair.resource_id for pair in pairs)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "INVENTORY_OBSERVATION_SIGNAL",
    "T0_RULE_EVALUATOR",
    "ExpectedRulePair",
    "RuleCoverage",
    "RuleEvidenceLimitation",
    "ScopedRuleCoverage",
    "WorkloadRuleResource",
    "activation_pin",
    "baseline_ref",
    "build_scoped_coverage",
    "canonical_sha256",
    "expected_rule_pairs",
]
