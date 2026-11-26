"""Immutable Cost Governance observation-campaign evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from fdai.shared.providers.cost_governance_lifecycle import (
    CostEvidenceKind,
    CostRevisionPin,
)

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class CostCampaignOutcome(StrEnum):
    """Separate observation outcomes; none is implicitly successful."""

    BENEFICIAL_ACTION = "beneficial-action"
    NO_OP = "no-op"
    DENY = "deny"
    HOLD_UNRESOLVED = "hold-unresolved"
    APPROVAL = "approval"
    EXECUTE = "execute"
    ROLLBACK = "rollback"


class CostCampaignSettlement(StrEnum):
    """Independent effect-settlement states."""

    VERIFIED = "verified"
    FAILED = "failed"
    CENSORED = "censored"
    UNSCORABLE = "unscorable"


class CostValidationStopCondition(StrEnum):
    """Conditions that stop release review without granting authority."""

    ONTOLOGY_COMPETENCY_REGRESSION = "ontology-competency-regression"
    WRONG_TOPIC_OWNER = "wrong-topic-owner"
    MISSING_PROTECTED_OBJECTIVE = "missing-protected-objective"
    MISSING_SAFEGUARD = "missing-safeguard"
    MISSING_HARD_DEPENDENCY = "missing-hard-dependency"
    MISSING_EFFECT_PATH = "missing-effect-path"
    UNEXPLAINED_PARITY_DIFFERENCE = "unexplained-parity-difference"
    POLICY_ESCAPE = "policy-escape"
    OBJECTIVE_REGRESSION = "objective-regression"
    MISSING_SETTLEMENT = "missing-settlement"
    FAILED_ROLLBACK = "failed-rollback"
    DISCLOSURE_LEAK = "disclosure-leak"


@dataclass(frozen=True, slots=True)
class CostCampaignEpisode:
    """One append-only campaign episode bound to an exact revision."""

    schema_version: str
    campaign_id: str
    episode_id: str
    revision: int
    idempotency_key: str
    revision_pin_digest: str
    evidence_kind: CostEvidenceKind
    outcome: CostCampaignOutcome
    reason: str
    target_refs: tuple[str, ...]
    settlement_statuses: tuple[CostCampaignSettlement, ...]
    recovery_attempts: int
    policy_excluded: bool
    policy_escape: bool
    objective_regression: bool
    audit_complete: bool
    hard_dependencies_complete: bool
    unauthorized_disclosure: bool
    ontology_competency_passed: bool
    topic_owner_correct: bool
    protected_objectives_complete: bool
    safeguards_complete: bool
    effect_path_complete: bool
    parity_explained: bool
    rollback_evidence_complete: bool
    decision_correct: bool
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    retention_until: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("campaign episode schema_version MUST be 1.0.0")
        for name in ("campaign_id", "episode_id", "idempotency_key", "reason"):
            _text(name, getattr(self, name))
        if self.revision < 1 or not 0 <= self.recovery_attempts <= 7:
            raise ValueError("campaign revision and recovery attempts MUST be bounded")
        _digest("revision_pin_digest", self.revision_pin_digest)
        _aware("observed_at", self.observed_at)
        _aware("retention_until", self.retention_until)
        if self.retention_until <= self.observed_at:
            raise ValueError("campaign retention MUST follow observation")
        refs = tuple(dict.fromkeys(self.evidence_refs))
        if not 1 <= len(refs) <= 64:
            raise ValueError("campaign evidence_refs MUST contain 1..64 unique values")
        for ref in refs:
            _text("evidence_ref", ref)
        object.__setattr__(self, "evidence_refs", refs)
        targets = tuple(sorted(set(self.target_refs)))
        if not targets or len(targets) > 32:
            raise ValueError("campaign target_refs MUST contain 1..32 unique values")
        for target in targets:
            _text("target_ref", target)
        object.__setattr__(self, "target_refs", targets)
        object.__setattr__(self, "settlement_statuses", tuple(self.settlement_statuses))
        if self.legal_hold != (self.legal_hold_ref is not None):
            raise ValueError("campaign legal hold state and reference MUST match")
        if self.legal_hold_ref is not None:
            _text("legal_hold_ref", self.legal_hold_ref)
        if self.outcome is CostCampaignOutcome.BENEFICIAL_ACTION and (
            self.policy_excluded
            or not self.settlement_statuses
            or any(
                status is not CostCampaignSettlement.VERIFIED for status in self.settlement_statuses
            )
        ):
            raise ValueError(
                "beneficial action MUST be eligible and all effects independently verified"
            )

    @property
    def digest(self) -> str:
        """Return the canonical episode digest."""

        return _canonical_digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical versioned episode payload."""

        return {
            name: (
                value.value
                if isinstance(value, StrEnum)
                else [item.value for item in value]
                if name == "settlement_statuses"
                else list(value)
                if name in {"evidence_refs", "target_refs"}
                else value.isoformat()
                if isinstance(value, datetime)
                else value
            )
            for name, value in (
                (field, getattr(self, field)) for field in self.__dataclass_fields__
            )
        }


@dataclass(frozen=True, slots=True)
class CostCampaignReport:
    """Bounded deterministic accounting without collapsing negative outcomes."""

    schema_version: str
    campaign_id: str
    review_target_id: str | None
    revision_pin: CostRevisionPin
    sample_count: int
    eligible_count: int
    excluded_count: int
    beneficial_action_count: int
    no_op_count: int
    deny_count: int
    hold_unresolved_count: int
    approval_count: int
    execute_count: int
    rollback_count: int
    recovery_attempt_count: int
    verified_settlement_count: int
    failed_settlement_count: int
    censored_settlement_count: int
    unscorable_settlement_count: int
    policy_escape_count: int
    objective_regression_count: int
    audit_complete_count: int
    hard_dependency_complete_count: int
    unauthorized_disclosure_count: int
    correct_decision_count: int
    shadow_dwell_seconds: int
    evidence_kinds: tuple[CostEvidenceKind, ...]
    stop_conditions: tuple[CostValidationStopCondition, ...]
    approval_reason_counts: Mapping[str, int]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("campaign report schema_version MUST be 1.0.0")
        _text("campaign_id", self.campaign_id)
        if self.review_target_id is not None:
            _text("review_target_id", self.review_target_id)
        numeric = (
            getattr(self, field)
            for field in self.__dataclass_fields__
            if field.endswith("_count") or field in {"sample_count", "shadow_dwell_seconds"}
        )
        if any(value < 0 for value in numeric):
            raise ValueError("campaign report counts MUST be nonnegative")
        if self.eligible_count + self.excluded_count != self.sample_count:
            raise ValueError("campaign eligible and excluded counts MUST partition samples")
        if (
            self.beneficial_action_count
            + self.no_op_count
            + self.deny_count
            + self.hold_unresolved_count
            + self.approval_count
            + self.execute_count
            + self.rollback_count
            != self.sample_count
        ):
            raise ValueError("campaign outcomes MUST partition samples")
        if not 0 <= self.correct_decision_count <= self.eligible_count:
            raise ValueError("correct decision count MUST be bounded by eligible samples")
        if any(
            count > self.sample_count
            for count in (
                self.beneficial_action_count,
                self.policy_escape_count,
                self.objective_regression_count,
                self.audit_complete_count,
                self.hard_dependency_complete_count,
                self.unauthorized_disclosure_count,
            )
        ):
            raise ValueError("campaign episode-level counts MUST be bounded by samples")
        object.__setattr__(
            self,
            "approval_reason_counts",
            MappingProxyType(dict(sorted(self.approval_reason_counts.items()))),
        )
        if (
            any(count < 1 or not key for key, count in self.approval_reason_counts.items())
            or sum(self.approval_reason_counts.values()) != self.approval_count
        ):
            raise ValueError("campaign approval reasons MUST partition approvals")
        for key in self.approval_reason_counts:
            _text("approval_reason", key)
        object.__setattr__(
            self,
            "evidence_kinds",
            tuple(sorted(set(self.evidence_kinds), key=str)),
        )
        object.__setattr__(
            self,
            "stop_conditions",
            tuple(sorted(set(self.stop_conditions), key=str)),
        )
        refs = tuple(dict.fromkeys(self.evidence_refs))
        if not 1 <= len(refs) <= 640_000:
            raise ValueError("campaign report evidence refs MUST be non-empty and bounded")
        for ref in refs:
            _text("evidence_ref", ref)
        object.__setattr__(self, "evidence_refs", refs)
        if not self.evidence_kinds:
            raise ValueError("campaign report MUST retain at least one evidence kind")

    @property
    def accuracy(self) -> Decimal:
        """Return eligible decision accuracy without credit for exclusions."""

        if self.eligible_count == 0:
            return Decimal("0")
        return Decimal(self.correct_decision_count) / Decimal(self.eligible_count)

    @property
    def digest(self) -> str:
        """Return the canonical report digest used by readiness results."""

        return _canonical_digest(
            {
                "campaign_id": self.campaign_id,
                "review_target_id": self.review_target_id,
                "approval_reason_counts": dict(self.approval_reason_counts),
                "counts": {
                    field: getattr(self, field)
                    for field in self.__dataclass_fields__
                    if field.endswith("_count") or field == "sample_count"
                },
                "evidence_kinds": [item.value for item in self.evidence_kinds],
                "evidence_refs": list(self.evidence_refs),
                "revision_pin_digest": self.revision_pin.digest,
                "schema_version": self.schema_version,
                "shadow_dwell_seconds": self.shadow_dwell_seconds,
                "stop_conditions": [item.value for item in self.stop_conditions],
            }
        )


class CostCampaignStore(Protocol):
    """Append campaign revisions and expose read-only retained evidence."""

    async def append_cost_campaign_episode(
        self,
        episode: CostCampaignEpisode,
        *,
        expected_revision: int,
    ) -> bool: ...

    async def read_cost_campaign_episodes(
        self,
        campaign_id: str,
        revision_pin_digest: str,
        *,
        limit: int,
    ) -> tuple[CostCampaignEpisode, ...]: ...


def _text(name: str, value: str) -> None:
    if not value or not value.isascii() or len(value) > 512:
        raise ValueError(f"{name} MUST be non-empty bounded ASCII")


def _digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST use lowercase sha256:<digest>")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CostCampaignEpisode",
    "CostCampaignOutcome",
    "CostCampaignReport",
    "CostCampaignSettlement",
    "CostCampaignStore",
    "CostValidationStopCondition",
]
