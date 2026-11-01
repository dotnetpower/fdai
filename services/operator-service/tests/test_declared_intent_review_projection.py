"""Tests for protected declared-intent exact-diff review projection and general-topic privacy."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fdai_operator_service.declared_intent_review_projection import (
    DeclaredIntentReviewAccessError,
    DeclaredIntentReviewerContext,
    DeclaredIntentSourceAccessMetadata,
    build_declared_intent_general_topic_summary,
    build_declared_intent_review_projection,
)
from fdai_service_contracts.document_intent import (
    DocumentIntentDiff,
    DocumentIntentEvent,
    IntentServiceProperties,
)

DOC_ID = UUID(int=1)
VER_ID = UUID(int=2)
DIGEST_A = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64
DIGEST_C = "sha256:" + "3" * 64
DIGEST_D = "sha256:" + "4" * 64


def _diff(*, operation: str = "add", expected_revision: int = 0) -> DocumentIntentDiff:
    return DocumentIntentDiff(
        operation=operation,  # type: ignore[arg-type]
        document_id=DOC_ID,
        version_id=VER_ID,
        source_revision=3,
        source_digest=DIGEST_A,
        envelope_digest=DIGEST_B,
        acl_digest=DIGEST_C,
        ontology_release=DIGEST_D,
        expected_revision=expected_revision,
        scope_ref="scope:payments-prod",
        requester_ref="principal:requester-1",
        properties=IntentServiceProperties(
            id="service:payments-core",
            name="Payments Core Service",
            criticality="tier-0",
            effective_from=datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
            effective_to=datetime(2027, 11, 1, 0, 0, tzinfo=UTC),
            source_ref=f"doc:{DOC_ID}:{VER_ID}",
        ),
    )


def _source() -> DeclaredIntentSourceAccessMetadata:
    return DeclaredIntentSourceAccessMetadata(
        document_id=str(DOC_ID),
        version_id=str(VER_ID),
        revision=3,
        uploader_id="principal:uploader-1",
        reader_groups=frozenset({"group:payments-architecture"}),
    )


def test_protected_review_projection_requires_role_independence_scope_and_acl() -> None:
    diff = _diff()
    source = _source()

    # Unauthenticated caller is rejected with 401.
    with pytest.raises(DeclaredIntentReviewAccessError) as unauth_exc:
        build_declared_intent_review_projection(diff=diff, source=source, reviewer=None)
    assert unauth_exc.value.status_code == 401
    assert unauth_exc.value.code == "unauthenticated"

    # Reader role cannot access the protected review surface.
    reader_ctx = DeclaredIntentReviewerContext(
        principal_id="principal:reviewer-1",
        roles=frozenset({"Reader"}),
        allowed_scopes=frozenset({"scope:payments-prod"}),
        group_ids=frozenset({"group:payments-architecture"}),
    )
    with pytest.raises(DeclaredIntentReviewAccessError) as role_exc:
        build_declared_intent_review_projection(diff=diff, source=source, reviewer=reader_ctx)
    assert role_exc.value.code == "missing_review_role"

    # Requester or uploader cannot review their own proposal.
    requester_ctx = DeclaredIntentReviewerContext(
        principal_id="principal:requester-1",
        roles=frozenset({"Approver"}),
        allowed_scopes=frozenset({"scope:payments-prod"}),
        group_ids=frozenset({"group:payments-architecture"}),
    )
    with pytest.raises(DeclaredIntentReviewAccessError) as self_exc:
        build_declared_intent_review_projection(diff=diff, source=source, reviewer=requester_ctx)
    assert self_exc.value.code == "non_independent_reviewer"

    # Out-of-scope reviewer is denied.
    wrong_scope_ctx = DeclaredIntentReviewerContext(
        principal_id="principal:reviewer-1",
        roles=frozenset({"Approver"}),
        allowed_scopes=frozenset({"scope:other"}),
        group_ids=frozenset({"group:payments-architecture"}),
    )
    with pytest.raises(DeclaredIntentReviewAccessError) as scope_exc:
        build_declared_intent_review_projection(
            diff=diff,
            source=source,
            reviewer=wrong_scope_ctx,
        )
    assert scope_exc.value.code == "scope_denied"

    # Owner without source ACL reader_groups is denied (no Owner bypass).
    owner_without_acl = DeclaredIntentReviewerContext(
        principal_id="principal:owner-no-acl",
        roles=frozenset({"Owner"}),
        allowed_scopes=frozenset({"scope:payments-prod"}),
        group_ids=frozenset({"group:unrelated"}),
    )
    with pytest.raises(DeclaredIntentReviewAccessError) as acl_exc:
        build_declared_intent_review_projection(
            diff=diff,
            source=source,
            reviewer=owner_without_acl,
        )
    assert acl_exc.value.code == "source_acl_denied"


def test_authorized_independent_reviewer_receives_exact_diff_with_no_authority() -> None:
    diff = _diff(operation="update", expected_revision=2)
    prior = IntentServiceProperties(
        id="service:payments-core",
        name="Payments Legacy Service",
        criticality="tier-1",
        effective_from=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        effective_to=None,
        source_ref=f"doc:{DOC_ID}:{VER_ID}",
    )
    reviewer = DeclaredIntentReviewerContext(
        principal_id="principal:approver-independent",
        roles=frozenset({"Approver"}),
        allowed_scopes=frozenset({"scope:payments-prod"}),
        group_ids=frozenset({"group:payments-architecture"}),
    )

    projection = build_declared_intent_review_projection(
        diff=diff,
        source=_source(),
        reviewer=reviewer,
        prior_properties=prior,
    )

    assert projection["read_only"] is True
    assert projection["authority"] == "none"
    assert projection["execution_authority"] is False
    assert projection["protected_surface"] is True
    assert projection["general_topic_safe"] is False
    assert projection["independent_reviewer"] is True
    assert projection["intent_digest"] == diff.digest
    assert projection["operation"] == "update"
    assert projection["expected_revision"] == 2

    changes = projection["property_changes"]
    assert isinstance(changes, list)
    changed_fields = {item["field_name"] for item in changes if item["changed"]}
    assert changed_fields == {"name", "criticality", "effective_from", "effective_to"}
    assert projection["changed_field_count"] == 4
    assert str(projection["review_projection_digest"]).startswith("sha256:")
    assert len(str(projection["review_projection_digest"])) == 71


def test_general_topic_summary_never_discloses_source_properties() -> None:
    diff = _diff()
    event = DocumentIntentEvent.create(
        "candidate",
        diff.digest,
        f"document-intent:{diff.digest[7:]}",
    )
    summary = build_declared_intent_general_topic_summary(event=event)

    assert summary["read_only"] is True
    assert summary["authority"] == "none"
    assert summary["execution_authority"] is False
    assert summary["general_topic_safe"] is True
    assert summary["discloses_source_properties"] is False
    assert str(summary["summary_digest"]).startswith("sha256:")
    assert len(str(summary["summary_digest"])) == 71

    serialized = json.dumps(summary)
    for confidential in (
        "Payments Core Service",
        "service:payments-core",
        "tier-0",
        str(DOC_ID),
        str(VER_ID),
    ):
        assert confidential not in serialized

    with pytest.raises(ValueError, match="MUST NOT disclose source property fields"):
        build_declared_intent_general_topic_summary(
            event=event,
            extra_fields={"properties": {"name": "Payments Core Service"}},
        )


def test_protected_review_projection_rejects_stale_or_non_governed_source_posture() -> None:
    diff = _diff()
    reviewer = DeclaredIntentReviewerContext(
        principal_id="principal:approver-independent",
        roles=frozenset({"Approver"}),
        allowed_scopes=frozenset({"scope:payments-prod"}),
        group_ids=frozenset({"group:payments-architecture"}),
    )
    stale_source = DeclaredIntentSourceAccessMetadata(
        document_id=str(DOC_ID),
        version_id=str(VER_ID),
        revision=99,
        uploader_id="principal:uploader-1",
        reader_groups=frozenset({"group:payments-architecture"}),
    )
    with pytest.raises(DeclaredIntentReviewAccessError) as rev_exc:
        build_declared_intent_review_projection(
            diff=diff,
            source=stale_source,
            reviewer=reviewer,
        )
    assert rev_exc.value.status_code == 409
    assert rev_exc.value.code == "source_revision_mismatch"


def test_reviewer_current_as_of_requires_timezone_aware_datetime() -> None:
    naive_now = datetime(2026, 11, 1, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        DeclaredIntentReviewerContext(
            principal_id="principal:approver-independent",
            roles=frozenset({"Approver"}),
            allowed_scopes=frozenset({"scope:payments-prod"}),
            group_ids=frozenset({"group:payments-architecture"}),
            current_as_of=naive_now,
        )

    aware_reviewer = DeclaredIntentReviewerContext(
        principal_id="principal:approver-independent",
        roles=frozenset({"Approver"}),
        allowed_scopes=frozenset({"scope:payments-prod"}),
        group_ids=frozenset({"group:payments-architecture"}),
        current_as_of=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
    )
    projection = build_declared_intent_review_projection(
        diff=_diff(),
        source=_source(),
        reviewer=aware_reviewer,
    )
    assert projection["independent_reviewer"] is True
    assert projection["changed_field_count"] == 6

    for bad_kwargs in (
        {"document_id": "   ", "version_id": str(VER_ID), "revision": 1},
        {"document_id": str(DOC_ID), "version_id": "", "revision": 1},
        {"document_id": str(DOC_ID), "version_id": str(VER_ID), "revision": 0},
        {"document_id": str(DOC_ID), "version_id": str(VER_ID), "revision": -2},
    ):
        with pytest.raises(DeclaredIntentReviewAccessError):
            DeclaredIntentSourceAccessMetadata(
                uploader_id="principal:uploader-1",
                reader_groups=frozenset({"group:payments-architecture"}),
                **bad_kwargs,  # type: ignore[arg-type]
            )
