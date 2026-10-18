"""Closed prior-authority and exact-request gates; no generated human approval."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai_service_contracts.cloud_knowledge_application import (
    CloudApplicationPolicy,
    CloudApplicationRequest,
    CloudPolicyAuthority,
    validate_application,
)
from pydantic import ValidationError

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def policy(**updates):
    return CloudApplicationPolicy.model_validate(
        dict(
            policy_id="reference",
            revision=1,
            collection_id="reference",
            registry_digest="a" * 64,
            requester_ids=("requester",),
            reader_groups=("readers",),
            source_ids=("source",),
            normalizer_versions=("1.0.0",),
            manifest_versions=("fdai.cloud-knowledge.v2",),
            max_bytes=1048576,
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            stop_condition="Any gate failure",
            tested_rollback_ref="reviewed-recovery:test",
            successful_dry_run_ref="reviewed-dry-run:test",
        )
        | updates
    )


def authority(**updates):
    return CloudPolicyAuthority.model_validate(
        dict(
            policy=policy(),
            author_id="author",
            approved_by="reviewer",
            approved_at=NOW - timedelta(hours=1),
        )
        | updates
    )


def request(**updates):
    return CloudApplicationRequest.model_validate(
        dict(
            nonce=uuid4(),
            policy_digest=policy().digest,
            requester_id="requester",
            upload_id=uuid4(),
            document_id=uuid4(),
            version_id=uuid4(),
            manifest_digest="b" * 64,
            manifest_version="fdai.cloud-knowledge.v2",
            normalizer_versions=("1.0.0",),
            index_input_digest="c" * 64,
            collection_id="reference",
            expected_active_version_id=None,
            idempotency_key="apply:exact",
            requested_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )
        | updates
    )


def validate(a=None, r=None, **updates):
    validate_application(
        a or authority(),
        r or request(),
        **(
            dict(
                now=NOW,
                requester_id="requester",
                manifest_digest="b" * 64,
                index_input_digest="c" * 64,
                collection_id="reference",
                registry_digest="a" * 64,
                source_ids=("source",),
                reader_groups=("readers",),
            )
            | updates
        ),
    )


def test_prior_independent_policy_accepts_exact_request():
    validate()


@pytest.mark.parametrize(
    "updates",
    [
        {"approved_by": "author"},
        {"approved_by": "requester"},
        {"approved_by": None},
        {"approved_at": None},
        {"approved_at": NOW + timedelta(seconds=1)},
        {"revoked_at": NOW},
        {"author_id": "reviewer"},
    ],
)
def test_authority_cannot_self_grant_or_outlive_revocation(updates):
    with pytest.raises(ValueError, match="authority"):
        validate(a=authority(**updates))


@pytest.mark.parametrize(
    "updates",
    [
        {"requester_id": "different"},
        {"manifest_digest": "d" * 64},
        {"index_input_digest": "e" * 64},
        {"collection_id": "another"},
        {"registry_digest": "f" * 64},
        {"source_ids": ("other",)},
        {"reader_groups": ("other",)},
        {"now": NOW + timedelta(minutes=10)},
        {"now": NOW - timedelta(seconds=1)},
    ],
)
def test_current_exact_request_scope_is_required(updates):
    with pytest.raises(ValueError):
        validate(**updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"requester_ids": ("*",)},
        {"requester_ids": ("requester", "requester")},
        {"source_ids": ()},
        {"reader_groups": ("",)},
        {"manifest_versions": ()},
        {"request_ttl_seconds": 3601},
        {"max_bytes": 16777217},
        {"valid_until": NOW - timedelta(days=2)},
    ],
)
def test_policy_setup_rejects_permissive_or_unbounded_scope(updates):
    with pytest.raises(ValidationError):
        policy(**updates)


def test_policy_amendment_does_not_renew_prior_request():
    revised = authority(policy=policy(revision=2))
    with pytest.raises(ValueError, match="binding"):
        validate(a=revised)


def test_policy_approved_after_request_cannot_backdate_authority():
    with pytest.raises(ValueError):
        validate(
            a=authority(approved_at=NOW + timedelta(seconds=1)), now=NOW + timedelta(seconds=2)
        )


@pytest.mark.parametrize("field", ["valid_from", "valid_until"])
def test_policy_rejects_naive_authority_times(field):
    with pytest.raises(ValidationError, match="timezone"):
        policy(**{field: NOW.replace(tzinfo=None)})


@pytest.mark.parametrize("field", ["requested_at", "expires_at"])
def test_request_rejects_naive_authority_times(field):
    with pytest.raises(ValidationError, match="timezone"):
        request(**{field: NOW.replace(tzinfo=None)})


@pytest.mark.parametrize("field", ["approved_at", "revoked_at"])
def test_human_policy_records_reject_naive_times(field):
    with pytest.raises(ValidationError, match="timezone"):
        authority(**{field: NOW.replace(tzinfo=None)})


def test_unknown_clock_cannot_grant_prior_authority():
    with pytest.raises(ValueError, match="authority"):
        authority().require_current("requester", NOW.replace(tzinfo=None))
