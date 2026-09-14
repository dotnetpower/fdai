"""Source-date contracts never confuse transport recency with source freshness."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.cloud_knowledge import (
    DAY,
    Applicability,
    CloudSourceEvidence,
    Freshness,
    RefreshPolicy,
    SourceCheckReceipt,
    content_digest,
    public_document_url,
)
from fdai_service_contracts.cloud_knowledge_release import (
    CloudKnowledgeDocument,
    KnowledgeReleaseManifest,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)
URL = "https://example.com/apim/network"


def evidence(*, at: datetime = NOW, policy: RefreshPolicy = RefreshPolicy()) -> CloudSourceEvidence:
    digest = content_digest(b"original")
    return CloudSourceEvidence(
        source_id="apim",
        source_url=URL,
        source_sha256=digest,
        normalized_sha256=content_digest(b"normalized"),
        collected_at=at,
        check=SourceCheckReceipt(
            source_id="apim",
            source_url=URL,
            content_sha256=digest,
            checked_at=at,
            outcome="fetched",
            equivalence="body_hash",
            collector_id="fixture",
        ),
        applicability=Applicability(
            resource_type="Microsoft.ApiManagement/service",
            service_generation="classic",
            skus=("Premium",),
        ),
        policy=policy,
        license_ref="reference-fixture",
    )


@pytest.mark.parametrize(
    ("seconds", "state"),
    [
        (0, Freshness.FRESH),
        (7 * DAY - 1, Freshness.FRESH),
        (7 * DAY, Freshness.REFRESH_DUE),
        (30 * DAY - 1, Freshness.REFRESH_DUE),
        (30 * DAY, Freshness.STALE),
        (90 * DAY, Freshness.STALE),
    ],
)
def test_weekly_exact_boundaries(seconds: int, state: Freshness) -> None:
    assert evidence().freshness(NOW + timedelta(seconds=seconds)) is state


def test_monthly_and_future_clock() -> None:
    item = evidence(
        policy=RefreshPolicy(
            check_interval_seconds=30 * DAY,
            max_unverified_seconds=90 * DAY,
        ),
    )
    assert item.freshness(NOW + timedelta(days=30)) is Freshness.REFRESH_DUE
    assert item.freshness(NOW + timedelta(days=90)) is Freshness.STALE
    assert item.freshness(NOW - timedelta(seconds=1)) is Freshness.UNKNOWN
    with pytest.raises(ValueError, match="timezone"):
        item.freshness(datetime(2026, 9, 14))


def test_new_package_does_not_make_old_source_fresh() -> None:
    old = evidence(at=NOW - timedelta(days=44))
    doc = CloudKnowledgeDocument(
        evidence=old,
        title="Reference",
        original_text="original",
        text="normalized",
    )
    release = KnowledgeReleaseManifest(
        release_id="release-1",
        sequence=1,
        collection_id="cloud",
        registry_digest="a" * 64,
        package_created_at=NOW,
        expires_at=NOW + timedelta(days=7),
        documents=(doc,),
    )
    assert release.documents[0].evidence.freshness(NOW) is Freshness.STALE
    assert not old.allows_current_guidance(NOW)
    assert not evidence().allows_current_guidance(NOW, update_pending=True)


def test_receipt_must_confirm_same_body_and_origin() -> None:
    item = evidence()
    for change in (
        {"content_sha256": "f" * 64},
        {"source_url": "https://example.com/other"},
        {"checked_at": NOW - timedelta(seconds=1)},
    ):
        check = item.check.model_dump() | change
        with pytest.raises(ValidationError):
            CloudSourceEvidence.model_validate(item.model_dump() | {"check": check})


def test_strong_304_and_immutable_fetch_time() -> None:
    original = evidence(at=NOW - timedelta(days=10))
    updated = CloudSourceEvidence.model_validate(
        original.model_dump()
        | {
            "check": original.check.model_dump()
            | {
                "checked_at": NOW,
                "outcome": "unchanged",
                "equivalence": "strong_etag",
                "etag": '"revision-1"',
            },
        },
    )
    assert updated.collected_at == original.collected_at
    assert updated.freshness(NOW) is Freshness.FRESH
    assert original.freshness(NOW) is Freshness.REFRESH_DUE
    with pytest.raises(ValidationError, match="strong ETag"):
        SourceCheckReceipt.model_validate(updated.check.model_dump() | {"etag": 'W/"weak"'})


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/doc",
        "https://user:secret@example.com/doc",
        "https://example.com/doc?secret=value",
        "https://example.com/a/../b",
        "https://example.com/a%2fb",
        "https://example.com/doc#fragment",
        "https://example.com/doc\n",
        "https://example.com:8080/doc",
    ],
)
def test_noncanonical_source_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        public_document_url(url)


def test_applicability_never_equates_premium_and_premium_v2() -> None:
    actual = evidence().applicability
    assert actual.matches(actual)
    assert not actual.matches(actual.model_copy(update={"service_generation": "v2"}))
    assert not actual.matches(actual.model_copy(update={"skus": ("Developer",)}))
    assert not actual.matches(actual.model_copy(update={"skus": ()}))
    assert not actual.matches(actual.model_copy(update={"regions": ("region-a",)}))


def test_closed_models_and_strict_limits() -> None:
    for change in (
        {"check_interval_seconds": True},
        {"max_unverified_seconds": 60},
        {"grant_authority": True},
    ):
        with pytest.raises(ValidationError):
            RefreshPolicy.model_validate(change)
    with pytest.raises(ValidationError):
        CloudKnowledgeDocument(
            evidence=evidence(),
            title="Bad",
            original_text="different",
            text="normalized",
        )
