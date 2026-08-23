from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.rule_catalog.schema.model_lifecycle_review import (
    ModelLifecycleProposalReview,
    ModelLifecycleReviewStatus,
    evaluate_model_lifecycle_review,
)

_NOW = datetime(2026, 8, 23, tzinfo=UTC)
_PROPOSAL_DIGEST = "a" * 64
_SOURCE_DIGEST = "b" * 64


def _proposal(**changes: object) -> ModelLifecycleProposalReview:
    values: dict[str, object] = {
        "proposal_digest": _PROPOSAL_DIGEST,
        "source_models_digest": _SOURCE_DIGEST,
        "affected_capabilities": ("t1.embedding", "t2.reasoner.primary"),
        "opened_at": _NOW,
        "expires_at": _NOW + timedelta(days=7),
        "merged_at": None,
    }
    values.update(changes)
    return ModelLifecycleProposalReview(**values)  # type: ignore[arg-type]


def test_active_proposal_does_not_hold_current_mapping() -> None:
    decision = evaluate_model_lifecycle_review(
        _proposal(),
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=_NOW + timedelta(days=6),
    )

    assert decision.status is ModelLifecycleReviewStatus.ACTIVE
    assert decision.held_capabilities == ()
    assert decision.mapping_authority is False
    assert decision.execution_authority is False


def test_expiry_boundary_holds_only_declared_capabilities() -> None:
    proposal = _proposal(affected_capabilities=("t2.reasoner.primary",))

    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )

    assert decision.status is ModelLifecycleReviewStatus.HOLD
    assert decision.reason_code == "proposal_expired_unmerged"
    assert decision.held_capabilities == ("t2.reasoner.primary",)


def test_merged_proposal_does_not_hold() -> None:
    proposal = _proposal(merged_at=_NOW + timedelta(days=2))

    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=_NOW + timedelta(days=8),
    )

    assert decision.status is ModelLifecycleReviewStatus.MERGED
    assert decision.held_capabilities == ()


def test_superseded_source_does_not_hold_new_mapping() -> None:
    decision = evaluate_model_lifecycle_review(
        _proposal(),
        current_models_digest="c" * 64,
        evaluated_at=_NOW + timedelta(days=8),
    )

    assert decision.status is ModelLifecycleReviewStatus.STALE_SOURCE
    assert decision.reason_code == "proposal_source_superseded"
    assert decision.held_capabilities == ()


@pytest.mark.parametrize(
    ("proposal", "evaluated_at", "status", "reason_code"),
    [
        (
            _proposal(),
            _NOW + timedelta(days=1),
            ModelLifecycleReviewStatus.ACTIVE,
            "proposal_review_active",
        ),
        (
            _proposal(),
            _NOW + timedelta(days=7),
            ModelLifecycleReviewStatus.HOLD,
            "proposal_expired_unmerged",
        ),
        (
            _proposal(merged_at=_NOW + timedelta(days=1)),
            _NOW + timedelta(days=2),
            ModelLifecycleReviewStatus.MERGED,
            "proposal_merged",
        ),
    ],
)
def test_every_current_source_decision_has_no_authority(
    proposal: ModelLifecycleProposalReview,
    evaluated_at: datetime,
    status: ModelLifecycleReviewStatus,
    reason_code: str,
) -> None:
    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=evaluated_at,
    )

    assert decision.status is status
    assert decision.reason_code == reason_code
    assert decision.mapping_authority is False
    assert decision.execution_authority is False


def test_decision_digest_is_replay_stable() -> None:
    proposal = _proposal()
    first = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )
    second = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )

    assert first == second
    assert len(first.decision_digest) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"proposal_digest": "invalid"}, "proposal_digest"),
        ({"source_models_digest": "invalid"}, "source_models_digest"),
        ({"affected_capabilities": ()}, "at least one"),
        (
            {"affected_capabilities": ("t2.reasoner.primary", "t1.embedding")},
            "unique and sorted",
        ),
        ({"affected_capabilities": ("invalid",)}, "bounded T1/T2"),
        ({"expires_at": _NOW}, "after opened_at"),
        ({"opened_at": datetime(2026, 8, 23)}, "timezone-aware"),
        ({"merged_at": _NOW - timedelta(seconds=1)}, "MUST NOT precede"),
        ({"merged_at": _NOW + timedelta(days=8)}, "MUST NOT be after expires_at"),
    ],
)
def test_proposal_rejects_invalid_boundary(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _proposal(**changes)


def test_evaluation_rejects_future_merge_observation() -> None:
    proposal = _proposal(merged_at=_NOW + timedelta(days=2))

    with pytest.raises(ValueError, match="after evaluated_at"):
        evaluate_model_lifecycle_review(
            proposal,
            current_models_digest=_SOURCE_DIGEST,
            evaluated_at=_NOW + timedelta(days=1),
        )
