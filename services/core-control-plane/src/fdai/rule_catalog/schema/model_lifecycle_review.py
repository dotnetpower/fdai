"""Evaluate model lifecycle proposal expiry without changing model mappings."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_CAPABILITY = re.compile(r"^(t1|t2)\.[a-z][a-z0-9._-]{1,63}$")


class ModelLifecycleReviewStatus(StrEnum):
    """Describe the effect of one proposal on the current model source."""

    ACTIVE = "active"
    HOLD = "hold"
    MERGED = "merged"
    STALE_SOURCE = "stale_source"


@dataclass(frozen=True, slots=True)
class ModelLifecycleProposalReview:
    """Bind one review proposal to the model source it was derived from."""

    proposal_digest: str
    source_models_digest: str
    affected_capabilities: tuple[str, ...]
    opened_at: datetime
    expires_at: datetime
    merged_at: datetime | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_digest(self.proposal_digest, "proposal_digest")
        _require_digest(self.source_models_digest, "source_models_digest")
        if not self.affected_capabilities:
            raise ValueError("model lifecycle proposal MUST affect at least one capability")
        if self.affected_capabilities != tuple(sorted(set(self.affected_capabilities))):
            raise ValueError("model lifecycle affected capabilities MUST be unique and sorted")
        if any(_CAPABILITY.fullmatch(item) is None for item in self.affected_capabilities):
            raise ValueError("model lifecycle affected capability MUST be a bounded T1/T2 id")
        _require_aware(self.opened_at, "opened_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.opened_at:
            raise ValueError("model lifecycle expires_at MUST be after opened_at")
        if self.merged_at is not None:
            _require_aware(self.merged_at, "merged_at")
            if self.merged_at < self.opened_at:
                raise ValueError("model lifecycle merged_at MUST NOT precede opened_at")
            if self.merged_at > self.expires_at:
                raise ValueError("model lifecycle merged_at MUST NOT be after expires_at")
        if self.closed_at is not None:
            _require_aware(self.closed_at, "closed_at")
            if self.closed_at < self.opened_at:
                raise ValueError("model lifecycle closed_at MUST NOT precede opened_at")
        if self.merged_at is not None and self.closed_at is not None:
            raise ValueError("model lifecycle proposal MUST NOT be both merged and closed-unmerged")


@dataclass(frozen=True, slots=True)
class ModelLifecycleShadowReplayReceipt:
    """Bind frozen-scenario replay evidence to a lifecycle acceptance decision."""

    proposal_digest: str
    source_models_digest: str
    decision_digest: str
    result: str
    replayed_at: datetime
    scenario_set_digest: str

    def __post_init__(self) -> None:
        _require_digest(self.proposal_digest, "proposal_digest")
        _require_digest(self.source_models_digest, "source_models_digest")
        _require_digest(self.decision_digest, "decision_digest")
        _require_digest(self.scenario_set_digest, "scenario_set_digest")
        if self.result not in {"passed", "failed"}:
            raise ValueError("model lifecycle shadow replay result MUST be passed or failed")
        _require_aware(self.replayed_at, "replayed_at")


@dataclass(frozen=True, slots=True)
class ModelLifecycleReviewDecision:
    """Record a replayable hold decision with no mapping or execution authority."""

    status: ModelLifecycleReviewStatus
    reason_code: str
    held_capabilities: tuple[str, ...]
    proposal_digest: str
    source_models_digest: str
    evaluated_at: datetime
    decision_digest: str
    mapping_authority: bool = False
    execution_authority: bool = False


def evaluate_model_lifecycle_review(
    proposal: ModelLifecycleProposalReview,
    *,
    current_models_digest: str,
    evaluated_at: datetime,
    shadow_replay: ModelLifecycleShadowReplayReceipt | None = None,
) -> ModelLifecycleReviewDecision:
    """Evaluate one trusted proposal without granting mapping or execution authority."""

    _require_digest(current_models_digest, "current_models_digest")
    _require_aware(evaluated_at, "evaluated_at")
    if proposal.source_models_digest != current_models_digest:
        return _decision(
            proposal,
            status=ModelLifecycleReviewStatus.STALE_SOURCE,
            reason_code="proposal_source_superseded",
            held_capabilities=(),
            evaluated_at=evaluated_at,
        )
    if proposal.closed_at is not None:
        if proposal.closed_at > evaluated_at:
            raise ValueError("model lifecycle closed_at MUST NOT be after evaluated_at")
        return _decision(
            proposal,
            status=ModelLifecycleReviewStatus.HOLD,
            reason_code="proposal_closed_unmerged",
            held_capabilities=proposal.affected_capabilities,
            evaluated_at=evaluated_at,
        )
    if proposal.merged_at is not None:
        if proposal.merged_at > evaluated_at:
            raise ValueError("model lifecycle merged_at MUST NOT be after evaluated_at")
        shadow_replay_reason = _shadow_replay_hold_reason(
            proposal,
            shadow_replay=shadow_replay,
        )
        if shadow_replay_reason is not None:
            return _decision(
                proposal,
                status=ModelLifecycleReviewStatus.HOLD,
                reason_code=shadow_replay_reason,
                held_capabilities=proposal.affected_capabilities,
                evaluated_at=evaluated_at,
            )
        return _decision(
            proposal,
            status=ModelLifecycleReviewStatus.MERGED,
            reason_code="proposal_merged",
            held_capabilities=(),
            evaluated_at=evaluated_at,
        )
    if evaluated_at >= proposal.expires_at:
        return _decision(
            proposal,
            status=ModelLifecycleReviewStatus.HOLD,
            reason_code="proposal_expired_unmerged",
            held_capabilities=proposal.affected_capabilities,
            evaluated_at=evaluated_at,
        )
    return _decision(
        proposal,
        status=ModelLifecycleReviewStatus.ACTIVE,
        reason_code="proposal_review_active",
        held_capabilities=(),
        evaluated_at=evaluated_at,
    )


def model_lifecycle_acceptance_decision_digest(
    proposal: ModelLifecycleProposalReview,
) -> str:
    """Return the stable acceptance decision digest a shadow replay receipt must bind."""

    body = {
        "decision_kind": "model_lifecycle_registry_acceptance",
        "status": ModelLifecycleReviewStatus.MERGED.value,
        "reason_code": "proposal_merged",
        "held_capabilities": (),
        "proposal_digest": proposal.proposal_digest,
        "source_models_digest": proposal.source_models_digest,
        "mapping_authority": False,
        "execution_authority": False,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _shadow_replay_hold_reason(
    proposal: ModelLifecycleProposalReview,
    *,
    shadow_replay: ModelLifecycleShadowReplayReceipt | None,
) -> str | None:
    if shadow_replay is None:
        return "shadow_replay_missing"
    if (
        shadow_replay.proposal_digest != proposal.proposal_digest
        or shadow_replay.source_models_digest != proposal.source_models_digest
        or shadow_replay.decision_digest != model_lifecycle_acceptance_decision_digest(proposal)
    ):
        return "shadow_replay_mismatch"
    if shadow_replay.result != "passed":
        return "shadow_replay_failed"
    if shadow_replay.replayed_at < proposal.opened_at or (
        proposal.merged_at is not None and shadow_replay.replayed_at > proposal.merged_at
    ):
        return "shadow_replay_stale"
    return None


def _decision(
    proposal: ModelLifecycleProposalReview,
    *,
    status: ModelLifecycleReviewStatus,
    reason_code: str,
    held_capabilities: tuple[str, ...],
    evaluated_at: datetime,
) -> ModelLifecycleReviewDecision:
    body = {
        "status": status.value,
        "reason_code": reason_code,
        "held_capabilities": held_capabilities,
        "proposal_digest": proposal.proposal_digest,
        "source_models_digest": proposal.source_models_digest,
        "evaluated_at": evaluated_at.isoformat(),
        "mapping_authority": False,
        "execution_authority": False,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ModelLifecycleReviewDecision(
        status=status,
        reason_code=reason_code,
        held_capabilities=held_capabilities,
        proposal_digest=proposal.proposal_digest,
        source_models_digest=proposal.source_models_digest,
        evaluated_at=evaluated_at,
        decision_digest=digest,
    )


def _require_digest(value: str, field: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"model lifecycle {field} MUST be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"model lifecycle {field} MUST be timezone-aware")


__all__ = [
    "ModelLifecycleProposalReview",
    "ModelLifecycleReviewDecision",
    "ModelLifecycleReviewStatus",
    "ModelLifecycleShadowReplayReceipt",
    "evaluate_model_lifecycle_review",
    "model_lifecycle_acceptance_decision_digest",
]
