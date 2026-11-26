"""GitHub governance review metadata binding tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rbac.roles import Role
from fdai.delivery.gitops_pr.governance_review import (
    GitHubPullRequestReview,
    GitHubPullRequestReviewContext,
    GovernanceReviewMetadataError,
    VerifiedGitHubPrincipal,
    build_governance_review_request,
)
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceChangeClass,
    validate_governance_review,
)

_HEAD = "a" * 40
_PRIOR_HEAD = "b" * 40
_COMMITTED_AT = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)
_REVIEWED_AT = _COMMITTED_AT + timedelta(minutes=5)
_ATTESTED_AT = _REVIEWED_AT + timedelta(seconds=1)


def _principal(
    login: str,
    oid: str,
    role: Role,
    *,
    revision: str = _HEAD,
    attested_at: datetime = _ATTESTED_AT,
    phishing_resistant: bool = True,
) -> VerifiedGitHubPrincipal:
    return VerifiedGitHubPrincipal(
        github_login=login,
        oid=oid,
        roles=frozenset({role}),
        reviewed_revision=revision,
        attested_at=attested_at,
        phishing_resistant=phishing_resistant,
    )


def _review(
    login: str,
    *,
    state: str = "APPROVED",
    revision: str = _HEAD,
    submitted_at: datetime = _REVIEWED_AT,
) -> GitHubPullRequestReview:
    return GitHubPullRequestReview(
        reviewer_login=login,
        state=state,
        commit_id=revision,
        submitted_at=submitted_at,
    )


def _context(*reviews: GitHubPullRequestReview) -> GitHubPullRequestReviewContext:
    return GitHubPullRequestReviewContext(
        author_login="author",
        head_revision=_HEAD,
        head_committed_at=_COMMITTED_AT,
        reviews=reviews,
    )


def test_exact_revision_identity_bridge_clears_ordinary_review() -> None:
    request = build_governance_review_request(
        change_class=GovernanceChangeClass.RULE_AUTHORING,
        context=_context(_review("reviewer")),
        verified_principals=(
            _principal("author", "oid-author", Role.CONTRIBUTOR),
            _principal("reviewer", "oid-reviewer", Role.APPROVER),
        ),
    )

    decision = validate_governance_review(request)

    assert decision.allowed is True
    assert decision.counted_approver_oids == ("oid-reviewer",)


def test_latest_changes_requested_review_invalidates_prior_approval() -> None:
    request = build_governance_review_request(
        change_class=GovernanceChangeClass.RULE_AUTHORING,
        context=_context(
            _review("reviewer"),
            _review(
                "reviewer",
                state="CHANGES_REQUESTED",
                submitted_at=_REVIEWED_AT + timedelta(minutes=1),
            ),
        ),
        verified_principals=(
            _principal("author", "oid-author", Role.CONTRIBUTOR),
            _principal("reviewer", "oid-reviewer", Role.APPROVER),
        ),
    )

    decision = validate_governance_review(request)

    assert decision.allowed is False
    assert decision.satisfied_quorum == 0


def test_stale_review_remains_visible_to_authority_decision() -> None:
    request = build_governance_review_request(
        change_class=GovernanceChangeClass.RULE_AUTHORING,
        context=_context(_review("reviewer", revision=_PRIOR_HEAD)),
        verified_principals=(
            _principal("author", "oid-author", Role.CONTRIBUTOR),
            _principal("reviewer", "oid-reviewer", Role.APPROVER, revision=_PRIOR_HEAD),
        ),
    )

    decision = validate_governance_review(request)

    assert decision.allowed is False
    assert {issue.code for issue in decision.issues} == {"approval_stale", "quorum_not_met"}


def test_review_without_exact_verified_identity_fails_closed() -> None:
    with pytest.raises(
        GovernanceReviewMetadataError,
        match="reviewer MUST have a verified identity for the exact revision",
    ):
        build_governance_review_request(
            change_class=GovernanceChangeClass.RULE_AUTHORING,
            context=_context(_review("reviewer")),
            verified_principals=(
                _principal("author", "oid-author", Role.CONTRIBUTOR),
                _principal("reviewer", "oid-reviewer", Role.APPROVER, revision=_PRIOR_HEAD),
            ),
        )


def test_attestation_that_precedes_review_fails_closed() -> None:
    with pytest.raises(
        GovernanceReviewMetadataError,
        match="reviewer identity attestation MUST follow the observed event",
    ):
        build_governance_review_request(
            change_class=GovernanceChangeClass.RULE_AUTHORING,
            context=_context(_review("reviewer")),
            verified_principals=(
                _principal("author", "oid-author", Role.CONTRIBUTOR),
                _principal(
                    "reviewer",
                    "oid-reviewer",
                    Role.APPROVER,
                    attested_at=_REVIEWED_AT - timedelta(seconds=1),
                ),
            ),
        )


def test_high_risk_review_uses_attested_phishing_resistance() -> None:
    request = build_governance_review_request(
        change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
        context=_context(_review("reviewer-1"), _review("reviewer-2")),
        verified_principals=(
            _principal("author", "oid-author", Role.CONTRIBUTOR),
            _principal("reviewer-1", "oid-reviewer-1", Role.APPROVER),
            _principal(
                "reviewer-2",
                "oid-reviewer-2",
                Role.APPROVER,
                phishing_resistant=False,
            ),
        ),
    )

    decision = validate_governance_review(request)

    assert decision.allowed is False
    assert decision.satisfied_quorum == 1
    assert "approval_not_phishing_resistant" in {issue.code for issue in decision.issues}


def test_author_self_approval_is_blocked_by_authority_decision() -> None:
    request = build_governance_review_request(
        change_class=GovernanceChangeClass.RULE_AUTHORING,
        context=_context(_review("author")),
        verified_principals=(_principal("author", "oid-author", Role.APPROVER),),
    )

    decision = validate_governance_review(request)

    assert decision.allowed is False
    assert {issue.code for issue in decision.issues} == {"self_approval", "quorum_not_met"}
