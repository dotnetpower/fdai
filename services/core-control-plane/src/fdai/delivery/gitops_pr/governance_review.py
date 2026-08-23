"""Strict GitHub review metadata bridge for governance authority checks.

GitHub supplies review state, revision, and time. A deployment-owned identity
provider separately verifies the reviewer's Entra object id, FDAI roles, and
phishing-resistant approval assurance. This module joins those inputs without
performing network I/O and fails closed when either side is missing or differs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from fdai.core.rbac.roles import Role
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
)

_DECISIVE_REVIEW_STATES: Final = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})


class GovernanceReviewMetadataError(ValueError):
    """Raised when GitHub metadata cannot be bound to verified human identity."""


@dataclass(frozen=True, slots=True)
class GitHubPullRequestReview:
    """One GitHub review record returned for a pull request."""

    reviewer_login: str
    state: str
    commit_id: str
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedGitHubPrincipal:
    """Deployment-verified Entra identity bound to one GitHub login and revision."""

    github_login: str
    oid: str
    roles: frozenset[Role]
    reviewed_revision: str
    attested_at: datetime
    phishing_resistant: bool = False


@dataclass(frozen=True, slots=True)
class GitHubPullRequestReviewContext:
    """Bounded GitHub metadata for one pull-request head revision."""

    author_login: str
    head_revision: str
    head_committed_at: datetime
    reviews: tuple[GitHubPullRequestReview, ...] = ()
    co_author_oids: frozenset[str] = frozenset()
    committer_oids: frozenset[str] = frozenset()


def build_governance_review_request(
    *,
    change_class: GovernanceChangeClass,
    context: GitHubPullRequestReviewContext,
    verified_principals: tuple[VerifiedGitHubPrincipal, ...],
) -> GovernanceReviewRequest:
    """Join GitHub review facts to verified principals for deterministic review.

    ``verified_principals`` must come from a deployment-owned verifier. A GitHub
    login, PR trailer, or review body alone is not identity or authentication
    assurance. Every accepted attestation is exact-revision and time bound.
    """

    principal_index = _index_principals(verified_principals)
    author = _principal_for(
        principal_index,
        login=context.author_login,
        revision=context.head_revision,
        observed_at=context.head_committed_at,
        purpose="author",
    )
    approvals: list[GovernanceApproval] = []
    for review in _latest_decisive_reviews(context.reviews):
        if review.state.strip().upper() != "APPROVED":
            continue
        principal = _principal_for(
            principal_index,
            login=review.reviewer_login,
            revision=review.commit_id,
            observed_at=review.submitted_at,
            purpose="reviewer",
        )
        approvals.append(
            GovernanceApproval(
                approver=GovernancePrincipal(oid=principal.oid, roles=principal.roles),
                reviewed_revision=review.commit_id,
                approved_at=review.submitted_at,
                phishing_resistant=principal.phishing_resistant,
            )
        )
    return GovernanceReviewRequest(
        change_class=change_class,
        author=GovernancePrincipal(oid=author.oid, roles=author.roles),
        head_revision=context.head_revision,
        head_committed_at=context.head_committed_at,
        approvals=tuple(approvals),
        co_author_oids=context.co_author_oids,
        committer_oids=context.committer_oids,
    )


def _index_principals(
    principals: tuple[VerifiedGitHubPrincipal, ...],
) -> dict[tuple[str, str], VerifiedGitHubPrincipal]:
    index: dict[tuple[str, str], VerifiedGitHubPrincipal] = {}
    for principal in principals:
        key = (_normalize(principal.github_login), _normalize(principal.reviewed_revision))
        if not key[0] or not key[1] or not principal.oid.strip():
            raise GovernanceReviewMetadataError(
                "verified principal identity and revision MUST be non-empty"
            )
        if key in index:
            raise GovernanceReviewMetadataError(
                "verified principal identity MUST be unique per GitHub login and revision"
            )
        if not _is_absolute(principal.attested_at):
            raise GovernanceReviewMetadataError("principal attestation time MUST be timezone-aware")
        index[key] = principal
    return index


def _principal_for(
    index: dict[tuple[str, str], VerifiedGitHubPrincipal],
    *,
    login: str,
    revision: str,
    observed_at: datetime,
    purpose: str,
) -> VerifiedGitHubPrincipal:
    if not _is_absolute(observed_at):
        raise GovernanceReviewMetadataError(f"GitHub {purpose} time MUST be timezone-aware")
    key = (_normalize(login), _normalize(revision))
    principal = index.get(key)
    if principal is None:
        raise GovernanceReviewMetadataError(
            f"GitHub {purpose} MUST have a verified identity for the exact revision"
        )
    if principal.attested_at < observed_at:
        raise GovernanceReviewMetadataError(
            f"GitHub {purpose} identity attestation MUST follow the observed event"
        )
    return principal


def _latest_decisive_reviews(
    reviews: tuple[GitHubPullRequestReview, ...],
) -> tuple[GitHubPullRequestReview, ...]:
    latest: dict[str, GitHubPullRequestReview] = {}
    for review in reviews:
        state = review.state.strip().upper()
        if state not in _DECISIVE_REVIEW_STATES:
            continue
        if not _normalize(review.reviewer_login) or not _normalize(review.commit_id):
            raise GovernanceReviewMetadataError(
                "GitHub review login and commit id MUST be non-empty"
            )
        if not _is_absolute(review.submitted_at):
            raise GovernanceReviewMetadataError("GitHub review time MUST be timezone-aware")
        normalized = GitHubPullRequestReview(
            reviewer_login=review.reviewer_login,
            state=state,
            commit_id=review.commit_id,
            submitted_at=review.submitted_at,
        )
        login = _normalize(review.reviewer_login)
        prior = latest.get(login)
        if prior is None or normalized.submitted_at > prior.submitted_at:
            latest[login] = normalized
    return tuple(latest[login] for login in sorted(latest))


def _normalize(value: str) -> str:
    return value.strip().casefold()


def _is_absolute(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "GitHubPullRequestReview",
    "GitHubPullRequestReviewContext",
    "GovernanceReviewMetadataError",
    "VerifiedGitHubPrincipal",
    "build_governance_review_request",
]
