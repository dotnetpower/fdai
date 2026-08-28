"""Governance pull-request review-authority validation.

rule-governance.md delivers every governance change as a reviewed catalog-as-code pull
request: an operator authors the draft, separate approvers review it, high-risk classes
need a quorum of two phishing-resistant approvals, and nobody may approve their own
change. This module is the pure decision core of that gate. A thin CI boundary supplies
the review context (author, approvals, reviewed revision) and reports the decision.

Pure and I/O-free. The decision is review-only: it never merges, mutates a catalog, or
grants policy, approval, or execution authority. Role bags come from the shared
``fdai.core.rbac.roles`` matrix so the PR gate and the runtime gate cannot drift.

Fail-closed rules:

- An approval is counted only when it names a non-blank operator object id, reviews the
  exact pull-request head revision, was recorded after that revision, carries the
  capability required by the change class, and satisfies the phishing-resistant
  requirement of a high-risk class.
- Self-approval by the author, a recorded co-author, or the committer blocks the change
  even when other approvals already satisfy the quorum.
- Repeated approvals from one operator count once, so one operator can never satisfy a
  quorum of two.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from fdai.core.rbac.roles import Capability, Role, has_capability

_MIN_REVISION_LENGTH: Final = 40
_MAX_REVISION_LENGTH: Final = 64
_MAX_APPROVALS: Final = 64


class GovernanceChangeClass(StrEnum):
    """Governance pull-request classes with distinct review-authority requirements."""

    RULE_AUTHORING = "rule-authoring"
    ASSIGNMENT = "assignment"
    ENFORCE_PROMOTION = "enforce-promotion"
    EXEMPTION = "exemption"
    OVERRIDE = "override"
    RISK_CLASSIFICATION_LOOSENING = "risk-classification-loosening"
    RULE_RETIREMENT = "rule-retirement"


@dataclass(frozen=True, slots=True)
class ChangeClassRequirement:
    """Deterministic review requirement for one governance change class."""

    capability: Capability
    quorum: int
    phishing_resistant: bool
    owner_review: bool


_REQUIREMENTS: Final = MappingProxyType(
    {
        GovernanceChangeClass.RULE_AUTHORING: ChangeClassRequirement(
            capability=Capability.REVIEW_GOVERNANCE_PR,
            quorum=1,
            phishing_resistant=False,
            owner_review=False,
        ),
        GovernanceChangeClass.ASSIGNMENT: ChangeClassRequirement(
            capability=Capability.REVIEW_GOVERNANCE_PR,
            quorum=1,
            phishing_resistant=False,
            owner_review=False,
        ),
        GovernanceChangeClass.ENFORCE_PROMOTION: ChangeClassRequirement(
            capability=Capability.APPROVE_QUORUM_PROMOTION,
            quorum=2,
            phishing_resistant=True,
            owner_review=False,
        ),
        GovernanceChangeClass.EXEMPTION: ChangeClassRequirement(
            capability=Capability.APPROVE_EXEMPTION,
            quorum=2,
            phishing_resistant=True,
            owner_review=False,
        ),
        GovernanceChangeClass.OVERRIDE: ChangeClassRequirement(
            capability=Capability.APPROVE_OVERRIDE,
            quorum=2,
            phishing_resistant=True,
            owner_review=False,
        ),
        GovernanceChangeClass.RISK_CLASSIFICATION_LOOSENING: ChangeClassRequirement(
            capability=Capability.APPROVE_QUORUM_PROMOTION,
            quorum=2,
            phishing_resistant=True,
            owner_review=True,
        ),
        # A retirement disables a rule everywhere it would otherwise apply -
        # its blast radius is global, not the resource-group-equivalent
        # scope an override is bounded to. It therefore requires at least
        # the override's quorum-2/phishing-resistant bar plus the same
        # Owner-tier review the risk-classification-loosening class needs.
        GovernanceChangeClass.RULE_RETIREMENT: ChangeClassRequirement(
            capability=Capability.APPROVE_QUORUM_PROMOTION,
            quorum=2,
            phishing_resistant=True,
            owner_review=True,
        ),
    }
)
"""Read-only requirement table mirroring the rule-governance.md RBAC section."""


def requirement_for(change_class: GovernanceChangeClass) -> ChangeClassRequirement:
    """Return the review requirement for ``change_class``."""

    return _REQUIREMENTS[change_class]


@dataclass(frozen=True, slots=True)
class GovernancePrincipal:
    """One governance operator identified by a stable directory object id."""

    oid: str
    roles: frozenset[Role] = frozenset()


@dataclass(frozen=True, slots=True)
class GovernanceApproval:
    """One recorded pull-request approval claim awaiting deterministic validation."""

    approver: GovernancePrincipal
    reviewed_revision: str
    approved_at: datetime
    phishing_resistant: bool = False
    dismissed: bool = False


@dataclass(frozen=True, slots=True)
class GovernanceReviewRequest:
    """Review context for one governance pull request."""

    change_class: GovernanceChangeClass
    author: GovernancePrincipal
    head_revision: str
    head_committed_at: datetime
    approvals: tuple[GovernanceApproval, ...] = ()
    co_author_oids: frozenset[str] = frozenset()
    committer_oids: frozenset[str] = frozenset()

    def authorship_oids(self) -> frozenset[str]:
        """Return every normalized identity that authored or committed this change."""

        identities = {self.author.oid, *self.co_author_oids, *self.committer_oids}
        return frozenset(_normalize(oid) for oid in identities if _normalize(oid))


@dataclass(frozen=True, slots=True)
class ReviewAuthorityIssue:
    """One review-authority finding; ``blocking`` issues alone reject the change."""

    code: str
    message: str
    blocking: bool
    subject_oid: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewAuthorityDecision:
    """Review-only outcome of one governance pull-request authority evaluation."""

    change_class: GovernanceChangeClass
    allowed: bool
    required_quorum: int
    satisfied_quorum: int
    counted_approver_oids: tuple[str, ...] = ()
    issues: tuple[ReviewAuthorityIssue, ...] = ()
    grants_execution_authority: bool = field(default=False, init=False)


def _normalize(oid: str) -> str:
    return oid.strip().casefold()


def _is_revision(value: str) -> bool:
    normalized = _normalize(value)
    if not _MIN_REVISION_LENGTH <= len(normalized) <= _MAX_REVISION_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in normalized)


def _validate_author(request: GovernanceReviewRequest, issues: list[ReviewAuthorityIssue]) -> None:
    author_oid = _normalize(request.author.oid)
    if not author_oid:
        issues.append(
            ReviewAuthorityIssue(
                code="author_identity_missing",
                message="governance pull request MUST record the author object id",
                blocking=True,
            )
        )
    elif not has_capability(request.author.roles, Capability.AUTHOR_DRAFT_PR):
        issues.append(
            ReviewAuthorityIssue(
                code="author_not_authorized",
                message="governance pull-request author MUST hold draft authoring authority",
                blocking=True,
                subject_oid=author_oid,
            )
        )


def _count_approval(
    approval: GovernanceApproval,
    *,
    request: GovernanceReviewRequest,
    requirement: ChangeClassRequirement,
    head_committed_at: datetime | None,
    authorship: frozenset[str],
    counted: dict[str, GovernancePrincipal],
    issues: list[ReviewAuthorityIssue],
) -> None:
    """Validate one approval and add it to ``counted`` only when fully authorized.

    ``head_committed_at`` is ``None`` when the head commit time is not absolute. The
    freshness comparison is then unverifiable, so the approval never counts instead of
    being compared against an ambiguous local time.
    """

    if approval.dismissed:
        return
    approver_oid = _normalize(approval.approver.oid)
    if not approver_oid:
        issues.append(
            ReviewAuthorityIssue(
                code="approver_identity_missing",
                message="governance approval MUST record the approver object id",
                blocking=True,
            )
        )
        return
    if approver_oid in authorship:
        issues.append(
            ReviewAuthorityIssue(
                code="self_approval",
                message="an operator MUST NOT approve a governance change they authored",
                blocking=True,
                subject_oid=approver_oid,
            )
        )
        return
    if _normalize(approval.reviewed_revision) != _normalize(request.head_revision):
        issues.append(
            ReviewAuthorityIssue(
                code="approval_stale",
                message="governance approval MUST review the exact pull-request head revision",
                blocking=False,
                subject_oid=approver_oid,
            )
        )
        return
    if approval.approved_at.tzinfo is None or approval.approved_at.utcoffset() is None:
        issues.append(
            ReviewAuthorityIssue(
                code="approval_time_not_absolute",
                message="governance approval time MUST be timezone-aware",
                blocking=False,
                subject_oid=approver_oid,
            )
        )
        return
    if head_committed_at is None:
        issues.append(
            ReviewAuthorityIssue(
                code="approval_freshness_unverifiable",
                message=(
                    "governance approval freshness cannot be verified against an "
                    "ambiguous head commit time"
                ),
                blocking=False,
                subject_oid=approver_oid,
            )
        )
        return
    if approval.approved_at < head_committed_at:
        issues.append(
            ReviewAuthorityIssue(
                code="approval_precedes_head",
                message="governance approval MUST NOT precede the reviewed head revision",
                blocking=False,
                subject_oid=approver_oid,
            )
        )
        return
    if not has_capability(approval.approver.roles, requirement.capability):
        issues.append(
            ReviewAuthorityIssue(
                code="approver_role_missing",
                message=(
                    "governance approver MUST hold the capability required by the change class: "
                    f"{requirement.capability.value}"
                ),
                blocking=False,
                subject_oid=approver_oid,
            )
        )
        return
    if requirement.phishing_resistant and not approval.phishing_resistant:
        issues.append(
            ReviewAuthorityIssue(
                code="approval_not_phishing_resistant",
                message="high-risk governance approval MUST be phishing-resistant and action-bound",
                blocking=False,
                subject_oid=approver_oid,
            )
        )
        return
    if approver_oid in counted:
        issues.append(
            ReviewAuthorityIssue(
                code="duplicate_approver",
                message="repeated approvals from one operator count once toward the quorum",
                blocking=False,
                subject_oid=approver_oid,
            )
        )
        return
    counted[approver_oid] = approval.approver


def validate_governance_review(
    request: GovernanceReviewRequest,
) -> ReviewAuthorityDecision:
    """Return the review-only authority decision for one governance pull request.

    Every finding is reported so a reviewer sees the full remediation list at once. The
    change is allowed only when no blocking issue exists, the distinct counted approvals
    reach the class quorum, and an Owner-tier review is present when the class demands
    one. The decision never grants execution authority.
    """

    requirement = _REQUIREMENTS[request.change_class]
    issues: list[ReviewAuthorityIssue] = []
    head_committed_at: datetime | None = request.head_committed_at
    if not _is_revision(request.head_revision):
        issues.append(
            ReviewAuthorityIssue(
                code="head_revision_invalid",
                message="governance pull-request head revision MUST be a full commit id",
                blocking=True,
            )
        )
    if request.head_committed_at.tzinfo is None or request.head_committed_at.utcoffset() is None:
        head_committed_at = None
        issues.append(
            ReviewAuthorityIssue(
                code="head_time_not_absolute",
                message="governance pull-request head commit time MUST be timezone-aware",
                blocking=True,
            )
        )
    if len(request.approvals) > _MAX_APPROVALS:
        issues.append(
            ReviewAuthorityIssue(
                code="approval_count_exceeded",
                message="governance pull request exceeds the bounded approval limit",
                blocking=True,
            )
        )
    _validate_author(request, issues)
    authorship = request.authorship_oids()
    counted: dict[str, GovernancePrincipal] = {}
    for approval in request.approvals[:_MAX_APPROVALS]:
        _count_approval(
            approval,
            request=request,
            requirement=requirement,
            head_committed_at=head_committed_at,
            authorship=authorship,
            counted=counted,
            issues=issues,
        )
    if requirement.owner_review and not _has_owner(counted.values()):
        issues.append(
            ReviewAuthorityIssue(
                code="owner_review_missing",
                message="this governance change class requires an Owner-tier approval",
                blocking=True,
            )
        )
    if len(counted) < requirement.quorum:
        issues.append(
            ReviewAuthorityIssue(
                code="quorum_not_met",
                message=(
                    f"governance change class requires {requirement.quorum} distinct authorized "
                    f"approvals; {len(counted)} counted"
                ),
                blocking=True,
            )
        )
    return ReviewAuthorityDecision(
        change_class=request.change_class,
        allowed=not any(issue.blocking for issue in issues),
        required_quorum=requirement.quorum,
        satisfied_quorum=len(counted),
        counted_approver_oids=tuple(sorted(counted)),
        issues=tuple(issues),
    )


def _has_owner(principals: Iterable[GovernancePrincipal]) -> bool:
    return any(Role.OWNER in principal.roles for principal in principals)


__all__ = [
    "ChangeClassRequirement",
    "GovernanceApproval",
    "GovernanceChangeClass",
    "GovernancePrincipal",
    "GovernanceReviewRequest",
    "ReviewAuthorityDecision",
    "ReviewAuthorityIssue",
    "requirement_for",
    "validate_governance_review",
]
