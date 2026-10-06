"""Governance pull-request review-authority validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.rbac.roles import Role
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
    requirement_for,
    validate_governance_review,
)
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)

_HEAD = "a" * 40
_COMMITTED_AT = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
_APPROVED_AT = _COMMITTED_AT + timedelta(minutes=5)

_AUTHOR = GovernancePrincipal(oid="oid-author-1", roles=frozenset({Role.CONTRIBUTOR}))
_APPROVER_ONE = GovernancePrincipal(oid="oid-approver-1", roles=frozenset({Role.APPROVER}))
_APPROVER_TWO = GovernancePrincipal(oid="oid-approver-2", roles=frozenset({Role.APPROVER}))
_OWNER = GovernancePrincipal(oid="oid-owner-1", roles=frozenset({Role.OWNER}))
_READER = GovernancePrincipal(oid="oid-reader-1", roles=frozenset({Role.READER}))
_BREAK_GLASS = GovernancePrincipal(oid="oid-break-glass-1", roles=frozenset({Role.BREAK_GLASS}))
_EXECUTOR = GovernancePrincipal(oid="oid-executor-1", roles=frozenset({Role.OWNER}))


def _approval(
    approver: GovernancePrincipal,
    *,
    revision: str = _HEAD,
    approved_at: datetime = _APPROVED_AT,
    phishing_resistant: bool = True,
    dismissed: bool = False,
) -> GovernanceApproval:
    return GovernanceApproval(
        approver=approver,
        reviewed_revision=revision,
        approved_at=approved_at,
        phishing_resistant=phishing_resistant,
        dismissed=dismissed,
    )


def _request(
    change_class: GovernanceChangeClass,
    *approvals: GovernanceApproval,
    author: GovernancePrincipal = _AUTHOR,
    co_author_oids: frozenset[str] = frozenset(),
    committer_oids: frozenset[str] = frozenset(),
    head_revision: str = _HEAD,
    head_committed_at: datetime = _COMMITTED_AT,
    approval_profile: ApprovalProfileRevision | None = None,
) -> GovernanceReviewRequest:
    return GovernanceReviewRequest(
        change_class=change_class,
        author=author,
        head_revision=head_revision,
        head_committed_at=head_committed_at,
        approvals=approvals,
        co_author_oids=co_author_oids,
        committer_oids=committer_oids,
        approval_profile=approval_profile,
    )


def _profile(operator: GovernancePrincipal = _OWNER) -> ApprovalProfileRevision:
    payload = {
        "revision_id": "approval-profile-r1",
        "approval_profile": "single-operator-production",
        "executor_principal": _EXECUTOR.oid,
        "effective_from": _COMMITTED_AT.isoformat(),
        "operator_principal": operator.oid,
    }
    return ApprovalProfileRevision(
        revision_id=str(payload["revision_id"]),
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal=str(payload["executor_principal"]),
        policy_digest=approval_profile_policy_digest(payload),
        effective_from=_COMMITTED_AT,
        operator_principal=str(payload["operator_principal"]),
    )


def _multi_profile() -> ApprovalProfileRevision:
    payload = {
        "revision_id": "approval-profile-r0",
        "approval_profile": "multi-operator",
        "executor_principal": _EXECUTOR.oid,
        "effective_from": _COMMITTED_AT.isoformat(),
        "operator_principal": None,
    }
    return ApprovalProfileRevision(
        revision_id=str(payload["revision_id"]),
        approval_profile=ApprovalProfileKind.MULTI_OPERATOR,
        executor_principal=str(payload["executor_principal"]),
        policy_digest=approval_profile_policy_digest(payload),
        effective_from=_COMMITTED_AT,
    )


def _codes(decision) -> set[str]:
    return {issue.code for issue in decision.issues}


def test_single_approver_clears_an_ordinary_authoring_change() -> None:
    decision = validate_governance_review(
        _request(GovernanceChangeClass.RULE_AUTHORING, _approval(_APPROVER_ONE))
    )

    assert decision.allowed is True
    assert decision.issues == ()
    assert decision.required_quorum == 1
    assert decision.satisfied_quorum == 1
    assert decision.counted_approver_oids == ("oid-approver-1",)
    assert decision.grants_execution_authority is False


def test_enforce_promotion_requires_two_distinct_approvers() -> None:
    single = validate_governance_review(
        _request(GovernanceChangeClass.ENFORCE_PROMOTION, _approval(_APPROVER_ONE))
    )
    quorum = validate_governance_review(
        _request(
            GovernanceChangeClass.ENFORCE_PROMOTION,
            _approval(_APPROVER_ONE),
            _approval(_APPROVER_TWO),
        )
    )

    assert single.allowed is False
    assert "quorum_not_met" in _codes(single)
    assert quorum.allowed is True
    assert quorum.satisfied_quorum == 2


def test_repeated_approval_from_one_operator_counts_once() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.EXEMPTION,
            _approval(_APPROVER_ONE),
            _approval(_APPROVER_ONE, approved_at=_APPROVED_AT + timedelta(minutes=1)),
        )
    )

    assert decision.allowed is False
    assert decision.satisfied_quorum == 1
    assert _codes(decision) == {"duplicate_approver", "quorum_not_met"}


def test_self_approval_blocks_even_with_an_independent_quorum() -> None:
    approver_author = GovernancePrincipal(
        oid=_AUTHOR.oid, roles=frozenset({Role.CONTRIBUTOR, Role.APPROVER})
    )
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.OVERRIDE,
            _approval(approver_author),
            _approval(_APPROVER_ONE),
            _approval(_APPROVER_TWO),
        )
    )

    assert decision.allowed is False
    assert "self_approval" in _codes(decision)
    assert decision.satisfied_quorum == 2
    assert _AUTHOR.oid not in decision.counted_approver_oids


def test_co_author_and_committer_identities_cannot_approve() -> None:
    co_author = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_APPROVER_ONE),
            co_author_oids=frozenset({" OID-Approver-1 "}),
        )
    )
    committer = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_APPROVER_TWO),
            committer_oids=frozenset({"oid-approver-2"}),
        )
    )

    assert co_author.allowed is False
    assert committer.allowed is False
    assert _codes(co_author) == {"self_approval", "quorum_not_met"}
    assert _codes(committer) == {"self_approval", "quorum_not_met"}


def test_stale_approval_of_an_earlier_revision_is_not_counted() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.ASSIGNMENT,
            _approval(_APPROVER_ONE, revision="b" * 40),
        )
    )

    assert decision.allowed is False
    assert _codes(decision) == {"approval_stale", "quorum_not_met"}


def test_approval_recorded_before_the_head_revision_is_not_counted() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.ASSIGNMENT,
            _approval(_APPROVER_ONE, approved_at=_COMMITTED_AT - timedelta(seconds=1)),
        )
    )

    assert decision.allowed is False
    assert "approval_precedes_head" in _codes(decision)


def test_naive_approval_time_is_not_counted() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.ASSIGNMENT,
            _approval(_APPROVER_ONE, approved_at=datetime(2026, 8, 17, 1, 0)),  # noqa: DTZ001
        )
    )

    assert decision.allowed is False
    assert "approval_time_not_absolute" in _codes(decision)


def test_reader_and_break_glass_principals_cannot_approve_governance() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_READER),
            _approval(_BREAK_GLASS),
        )
    )

    assert decision.allowed is False
    assert decision.satisfied_quorum == 0
    assert _codes(decision) == {"approver_role_missing", "quorum_not_met"}


def test_high_risk_change_requires_phishing_resistant_approvals() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.EXEMPTION,
            _approval(_APPROVER_ONE, phishing_resistant=False),
            _approval(_APPROVER_TWO),
        )
    )

    assert decision.allowed is False
    assert "approval_not_phishing_resistant" in _codes(decision)
    assert decision.satisfied_quorum == 1


def test_risk_classification_loosening_requires_an_owner_review() -> None:
    without_owner = validate_governance_review(
        _request(
            GovernanceChangeClass.RISK_CLASSIFICATION_LOOSENING,
            _approval(_APPROVER_ONE),
            _approval(_APPROVER_TWO),
        )
    )
    with_owner = validate_governance_review(
        _request(
            GovernanceChangeClass.RISK_CLASSIFICATION_LOOSENING,
            _approval(_APPROVER_ONE),
            _approval(_OWNER),
        )
    )

    assert without_owner.allowed is False
    assert "owner_review_missing" in _codes(without_owner)
    assert with_owner.allowed is True


def test_standing_authority_promotion_requires_owner_tier_quorum_of_two() -> None:
    without_owner = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_APPROVER_ONE),
            _approval(_APPROVER_TWO),
        )
    )
    with_owner = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_APPROVER_ONE),
            _approval(_OWNER),
        )
    )

    assert without_owner.allowed is False
    assert "owner_review_missing" in _codes(without_owner)
    assert with_owner.allowed is True
    assert with_owner.required_quorum == 2
    assert with_owner.grants_execution_authority is False


def test_single_operator_profile_accepts_named_owner_for_standing_authority_promotion() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_OWNER),
            author=_OWNER,
            approval_profile=_profile(_OWNER),
        )
    )

    assert decision.allowed is True
    assert decision.required_quorum == 1
    assert decision.original_quorum == 2
    assert decision.effective_quorum == 1
    assert decision.counted_approver_oids == (_OWNER.oid,)
    assert decision.approval_profile == "single-operator-production"
    assert decision.operator_principal == _OWNER.oid
    assert decision.self_review is True
    assert decision.grants_execution_authority is False


def test_single_operator_profile_accepts_named_operator_for_override_promotion_only() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.OPERATOR_OVERRIDE_PROMOTION,
            _approval(_APPROVER_ONE),
            author=_APPROVER_ONE,
            approval_profile=_profile(_APPROVER_ONE),
        )
    )

    assert decision.allowed is True
    assert decision.required_quorum == 1
    assert decision.original_quorum == 2
    assert decision.effective_quorum == 1
    assert decision.counted_approver_oids == (_APPROVER_ONE.oid,)
    assert decision.approval_profile == "single-operator-production"
    assert decision.operator_principal == _APPROVER_ONE.oid
    assert decision.self_review is True


def test_single_operator_profile_refuses_unnamed_and_executor_principals() -> None:
    unnamed = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_APPROVER_ONE),
            author=_OWNER,
            approval_profile=_profile(_OWNER),
        )
    )
    executor = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_EXECUTOR),
            author=_OWNER,
            approval_profile=_profile(_OWNER),
        )
    )

    assert unnamed.allowed is False
    assert "approval_profile_unnamed_principal" in _codes(unnamed)
    assert executor.allowed is False
    assert "approval_profile_approver_is_executor" in _codes(executor)


def test_single_operator_profile_still_requires_owner_role_and_phishing_resistance() -> None:
    non_owner_profile = _profile(_APPROVER_ONE)
    non_owner = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_APPROVER_ONE),
            author=_APPROVER_ONE,
            approval_profile=non_owner_profile,
        )
    )
    weak_auth = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_OWNER, phishing_resistant=False),
            author=_OWNER,
            approval_profile=_profile(_OWNER),
        )
    )

    assert non_owner.allowed is False
    assert "owner_review_missing" in _codes(non_owner)
    assert weak_auth.allowed is False
    assert "approval_not_phishing_resistant" in _codes(weak_auth)


def test_multi_operator_and_other_classes_ignore_the_single_operator_profile() -> None:
    multi_self = validate_governance_review(
        _request(
            GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION,
            _approval(_OWNER),
            author=_OWNER,
            approval_profile=_multi_profile(),
        )
    )
    enforce_promotion = validate_governance_review(
        _request(
            GovernanceChangeClass.ENFORCE_PROMOTION,
            _approval(_OWNER),
            author=_OWNER,
            approval_profile=_profile(_OWNER),
        )
    )
    ordinary_override = validate_governance_review(
        _request(
            GovernanceChangeClass.OVERRIDE,
            _approval(_OWNER),
            author=_OWNER,
            approval_profile=_profile(_OWNER),
        )
    )

    assert multi_self.allowed is False
    assert _codes(multi_self) == {"owner_review_missing", "quorum_not_met", "self_approval"}
    assert multi_self.required_quorum == 2
    assert multi_self.approval_profile is None
    assert enforce_promotion.allowed is False
    assert _codes(enforce_promotion) == {"self_approval", "quorum_not_met"}
    assert enforce_promotion.required_quorum == 2
    assert enforce_promotion.approval_profile is None
    assert ordinary_override.allowed is False
    assert _codes(ordinary_override) == {"self_approval", "quorum_not_met"}
    assert ordinary_override.required_quorum == 2
    assert ordinary_override.approval_profile is None


def test_dismissed_approval_is_silently_uncounted() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_APPROVER_ONE, dismissed=True),
        )
    )

    assert decision.allowed is False
    assert _codes(decision) == {"quorum_not_met"}


def test_missing_or_unauthorized_author_identity_blocks_the_change() -> None:
    blank = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_APPROVER_ONE),
            author=GovernancePrincipal(oid="   ", roles=frozenset({Role.CONTRIBUTOR})),
        )
    )
    unauthorized = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_APPROVER_ONE),
            author=GovernancePrincipal(oid="oid-author-2", roles=frozenset({Role.READER})),
        )
    )

    assert blank.allowed is False
    assert "author_identity_missing" in _codes(blank)
    assert unauthorized.allowed is False
    assert "author_not_authorized" in _codes(unauthorized)


def test_blank_approver_identity_blocks_the_change() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(GovernancePrincipal(oid=" ", roles=frozenset({Role.APPROVER}))),
            _approval(_APPROVER_ONE),
        )
    )

    assert decision.allowed is False
    assert "approver_identity_missing" in _codes(decision)


def test_invalid_head_revision_blocks_the_change() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_APPROVER_ONE, revision="head"),
            head_revision="head",
        )
    )

    assert decision.allowed is False
    assert "head_revision_invalid" in _codes(decision)


def test_naive_head_commit_time_fails_closed_without_comparing_times() -> None:
    decision = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_AUTHORING,
            _approval(_APPROVER_ONE),
            head_committed_at=_COMMITTED_AT.replace(tzinfo=None),  # noqa: DTZ901
        )
    )

    assert decision.allowed is False
    assert decision.counted_approver_oids == ()
    assert {"head_time_not_absolute", "approval_freshness_unverifiable"} <= _codes(decision)


def test_rule_retirement_requires_owner_tier_quorum_of_two() -> None:
    sub_quorum = validate_governance_review(
        _request(GovernanceChangeClass.RULE_RETIREMENT, _approval(_APPROVER_ONE))
    )
    no_owner = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_RETIREMENT,
            _approval(_APPROVER_ONE),
            _approval(_APPROVER_TWO),
        )
    )
    cleared = validate_governance_review(
        _request(
            GovernanceChangeClass.RULE_RETIREMENT,
            _approval(_APPROVER_ONE),
            _approval(_OWNER),
        )
    )

    assert sub_quorum.allowed is False
    assert "quorum_not_met" in _codes(sub_quorum)
    assert no_owner.allowed is False
    assert "owner_review_missing" in _codes(no_owner)
    assert cleared.allowed is True
    assert cleared.required_quorum == 2


def test_every_change_class_declares_its_bounded_requirement() -> None:
    expected = {
        GovernanceChangeClass.RULE_AUTHORING: (1, False, False),
        GovernanceChangeClass.ASSIGNMENT: (1, False, False),
        GovernanceChangeClass.ENFORCE_PROMOTION: (2, True, False),
        GovernanceChangeClass.STANDING_AUTHORITY_PROMOTION: (2, True, True),
        GovernanceChangeClass.EXEMPTION: (2, True, False),
        GovernanceChangeClass.OVERRIDE: (2, True, False),
        GovernanceChangeClass.OPERATOR_OVERRIDE_PROMOTION: (2, True, False),
        GovernanceChangeClass.RISK_CLASSIFICATION_LOOSENING: (2, True, True),
        GovernanceChangeClass.RULE_RETIREMENT: (2, True, True),
    }

    assert set(expected) == set(GovernanceChangeClass)
    for change_class, (quorum, phishing_resistant, owner_review) in expected.items():
        requirement = requirement_for(change_class)
        assert requirement.quorum == quorum
        assert requirement.phishing_resistant is phishing_resistant
        assert requirement.owner_review is owner_review
