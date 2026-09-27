"""Durable Assurance Twin posture/review ledger tests.

Every case asks one question: can a reader replay the exact evidence a tip
announced, and does a contradicting redelivery fail closed instead of
silently keeping one truth in the ledger and publishing another?
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, TypedDict

import pytest
from fdai.core.assurance_twin import build_posture_assessment_report
from fdai.core.assurance_twin.report import PostureAssessmentReport
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    CONFLICT_MARKER_FIELD,
    POSTURE_CONFLICT_REASON_CODE,
    REVIEW_CONFLICT_REASON_CODE,
    StateStoreAssuranceTwinPostureLedger,
    change_review_state_key,
    evidence_body_digest,
    posture_report_state_key,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_SCOPE = "sub/00000000-0000-0000-0000-000000000001"


class _Provenance(TypedDict):
    activity_id: str
    correlation_id: str
    evidence_source_revision: str


_PROVENANCE: _Provenance = {
    "activity_id": "assurance-twin.change-review:k-1:completed",
    "correlation_id": "correlation-1",
    "evidence_source_revision": "sha256:feedface",
}


def _safe_identity(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _finding(
    rule: str = "r-1",
    ref: str = "vm-a",
    severity: str = "high",
    evidence_refs: tuple[str, ...] = (),
) -> Finding:
    return Finding(
        rule_id=rule,
        resource=ResourceRef(resource_type="compute.vm", ref=ref),
        severity=severity,  # type: ignore[arg-type]
        reason="reason",
        evidence_refs=evidence_refs,
    )


def _findings_batch(count: int) -> tuple[Finding, ...]:
    return tuple(_finding(rule=f"r-{i}", ref=f"vm-{i}") for i in range(count))


def _report(
    *findings: Finding,
    generated_at: str = "2026-07-07T00:00:00Z",
) -> PostureAssessmentReport:
    return build_posture_assessment_report(
        scope=_SCOPE,
        generated_at=generated_at,
        mode=Mode.SHADOW,
        findings=findings,
    )


def _review(
    key: str = "k-1",
    *findings: Finding,
    verdict: str = "needs_review",
    generated_at: str = "2026-07-07T00:00:00Z",
) -> IacReview:
    return IacReview(
        pr_ref="owner/repo#1",
        review_key=key,
        findings=findings,
        verdict=verdict,
        mode=Mode.SHADOW,
        generated_at=generated_at,
    )


async def test_posture_report_write_is_readable_and_overwrites_latest() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    first = await ledger.record_posture_report(
        _report(_finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert first.created is True
    assert first.key == posture_report_state_key(_SCOPE)

    read_back = await ledger.read_latest_posture_report(_SCOPE)
    assert read_back is not None
    assert read_back["scope"] == _SCOPE
    assert read_back["freshness"] == "fresh"
    assert len(read_back["findings"]) == 1

    # A report generated later for the same scope replaces the prior snapshot.
    second = await ledger.record_posture_report(
        _report(
            _finding(),
            _finding(rule="r-2"),
            generated_at="2026-07-07T01:00:00Z",
        ),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert second.created is True
    replaced = await ledger.read_latest_posture_report(_SCOPE)
    assert replaced is not None
    assert len(replaced["findings"]) == 2


async def test_delayed_older_posture_report_cannot_replace_newer_evidence() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    newer = await ledger.record_posture_report(
        _report(_finding(rule="new"), generated_at="2026-07-07T02:00:00Z"),
        freshness="fresh",
        **_PROVENANCE,
    )
    older = await ledger.record_posture_report(
        _report(_finding(rule="old"), generated_at="2026-07-07T01:00:00Z"),
        freshness="fresh",
        **_PROVENANCE,
    )

    assert newer.created is True
    assert older.created is False
    retained = await ledger.read_latest_posture_report(_SCOPE)
    assert retained is not None
    assert retained["generated_at"] == "2026-07-07T02:00:00+00:00"
    assert retained["findings"][0]["rule_id"] == "new"


async def test_concurrent_posture_reports_converge_on_newest_evidence() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    await asyncio.gather(
        ledger.record_posture_report(
            _report(_finding(rule="old"), generated_at="2026-07-07T01:00:00Z"),
            freshness="fresh",
            **_PROVENANCE,
        ),
        ledger.record_posture_report(
            _report(_finding(rule="new"), generated_at="2026-07-07T02:00:00Z"),
            freshness="fresh",
            **_PROVENANCE,
        ),
    )

    retained = await ledger.read_latest_posture_report(_SCOPE)
    assert retained is not None
    assert retained["generated_at"] == "2026-07-07T02:00:00+00:00"
    assert retained["findings"][0]["rule_id"] == "new"


async def test_same_timestamp_different_posture_evidence_is_tombstoned() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    first = await ledger.record_posture_report(
        _report(_finding(rule="first")),
        freshness="fresh",
        **_PROVENANCE,
    )
    conflicting = await ledger.record_posture_report(
        _report(_finding(rule="second")),
        freshness="fresh",
        **_PROVENANCE,
    )

    assert first.created is True
    assert conflicting.created is False
    assert conflicting.conflict is True
    retained = await ledger.read_latest_posture_report(_SCOPE)
    assert retained is not None
    assert retained["findings"][0]["rule_id"] == "first"
    marker = retained[CONFLICT_MARKER_FIELD]
    assert marker["reason_code"] == POSTURE_CONFLICT_REASON_CODE


async def test_concurrent_same_timestamp_posture_evidence_converges_on_conflict() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    outcomes = await asyncio.gather(
        ledger.record_posture_report(
            _report(_finding(rule="first")),
            freshness="fresh",
            **_PROVENANCE,
        ),
        ledger.record_posture_report(
            _report(_finding(rule="second")),
            freshness="fresh",
            **_PROVENANCE,
        ),
    )

    assert any(outcome.conflict for outcome in outcomes)
    retained = await ledger.read_latest_posture_report(_SCOPE)
    assert retained is not None
    assert retained[CONFLICT_MARKER_FIELD]["reason_code"] == POSTURE_CONFLICT_REASON_CODE


async def test_same_timestamp_identical_posture_evidence_is_idempotent() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    first = await ledger.record_posture_report(
        _report(_finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    replay = await ledger.record_posture_report(
        _report(_finding()),
        freshness="fresh",
        **_PROVENANCE,
    )

    assert first.created is True
    assert replay.created is False
    assert replay.conflict is False


async def test_posture_report_row_carries_replayable_provenance() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    write = await ledger.record_posture_report(
        _report(_finding()),
        freshness="fresh",
        **_PROVENANCE,
    )

    row = await ledger.read_latest_posture_report(_SCOPE)
    assert row is not None
    assert row["activity_id"] == _PROVENANCE["activity_id"]
    assert row["correlation_id"] == _safe_identity(_PROVENANCE["correlation_id"])
    assert row["evidence_source_revision"] == _PROVENANCE["evidence_source_revision"]
    assert row["evidence_digest"] == write.evidence_digest
    # The digest covers the evidence body only, so provenance never changes it.
    assert evidence_body_digest(row) == write.evidence_digest


async def test_change_review_write_is_idempotent_by_review_key() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    first = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert first.created is True
    assert first.conflict is False
    assert first.key == change_review_state_key("k-1")

    duplicate = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert duplicate.created is False
    assert duplicate.conflict is False
    assert duplicate.evidence_digest == first.evidence_digest
    assert len(store.audit_entries) == 1

    reviews = await ledger.read_recent_change_reviews(limit=10)
    assert len(reviews) == 1
    assert reviews[0]["review_key"] == "k-1"
    assert reviews[0]["findings"][0]["rule_id"] == "r-1"


async def test_unprojectable_review_enums_are_rejected_before_write() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    with pytest.raises(ValueError, match="review verdict is not projectable"):
        await ledger.record_change_review(
            _review("bad-verdict", verdict="typo"),
            freshness="fresh",
            **_PROVENANCE,
        )
    with pytest.raises(ValueError, match="finding severity is not projectable"):
        await ledger.record_change_review(
            _review("bad-severity", _finding(severity="typo")),
            freshness="fresh",
            **_PROVENANCE,
        )
    with pytest.raises(ValueError, match="freshness is not projectable"):
        await ledger.record_change_review(
            _review("bad-freshness"),
            freshness="typo",
            **_PROVENANCE,
        )

    assert await ledger.read_recent_change_reviews() == ()


async def test_identical_redelivery_under_a_new_correlation_stays_idempotent() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    await ledger.record_change_review(_review("k-1", _finding()), freshness="fresh", **_PROVENANCE)
    replay = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        activity_id="assurance-twin.change-review:k-1:completed",
        correlation_id="correlation-2",
        evidence_source_revision="sha256:feedface",
    )

    assert replay.created is False
    assert replay.conflict is False


async def test_equivalent_offset_timestamp_redelivery_stays_idempotent() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    first = await ledger.record_change_review(
        _review("k-1", _finding(), generated_at="2026-07-07T00:00:00Z"),
        freshness="fresh",
        **_PROVENANCE,
    )
    replay = await ledger.record_change_review(
        _review("k-1", _finding(), generated_at="2026-07-07T01:00:00+01:00"),
        freshness="fresh",
        **_PROVENANCE,
    )

    assert replay.created is False
    assert replay.conflict is False
    assert replay.evidence_digest == first.evidence_digest
    rows = await ledger.read_recent_change_reviews(limit=1)
    assert rows[0]["generated_at"] == "2026-07-07T00:00:00+00:00"


async def test_conflicting_redelivery_tombstones_the_row_and_keeps_the_stored_body() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    first = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    conflicting = await ledger.record_change_review(
        _review("k-1", _finding(rule="r-2"), verdict="blocked"),
        freshness="fresh",
        **_PROVENANCE,
    )

    assert conflicting.created is False
    assert conflicting.conflict is True
    assert conflicting.stored_evidence_digest == first.evidence_digest
    assert conflicting.evidence_digest != first.evidence_digest

    reviews = await ledger.read_recent_change_reviews(limit=10)
    assert len(reviews) == 1
    assert reviews[0]["verdict"] == "needs_review"
    assert reviews[0]["findings"][0]["rule_id"] == "r-1"
    # The durable marker is what makes an Operator API/Console read render
    # the row unavailable instead of serving one of two contradicting bodies.
    marker = reviews[0][CONFLICT_MARKER_FIELD]
    assert marker["reason_code"] == REVIEW_CONFLICT_REASON_CODE
    assert marker["stored_evidence_digest"] == first.evidence_digest
    assert marker["rejected_evidence_digest"] == conflicting.evidence_digest
    # The marker is write history, so the preserved body still verifies.
    assert evidence_body_digest(reviews[0]) == first.evidence_digest


async def test_conflict_marker_is_durable_across_later_redeliveries() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    first = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    await ledger.record_change_review(
        _review("k-1", _finding(rule="r-2"), verdict="blocked"),
        freshness="fresh",
        **_PROVENANCE,
    )

    # Replaying the originally stored body cannot clear the conflict.
    replay = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert replay.conflict is True
    assert replay.created is False
    assert replay.evidence_digest == first.evidence_digest

    rows = await ledger.read_recent_change_reviews(limit=10)
    assert len(rows) == 1
    assert rows[0][CONFLICT_MARKER_FIELD]["reason_code"] == REVIEW_CONFLICT_REASON_CODE
    assert rows[0]["verdict"] == "needs_review"


async def test_conflict_is_detected_against_a_row_without_recorded_provenance() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    legacy_body = {
        "pr_ref": "owner/repo#1",
        "review_key": "k-1",
        "verdict": "clear",
        "mode": "shadow",
        "generated_at": "2026-07-07T00:00:00Z",
        "freshness": "fresh",
        "reason_codes": [],
        "metadata": {},
        "findings": [],
    }
    await store.write_state(change_review_state_key("k-1"), legacy_body)

    conflicting = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )

    assert conflicting.conflict is True
    assert conflicting.stored_evidence_digest == evidence_body_digest(legacy_body)


async def test_legacy_offset_timestamp_replay_does_not_create_a_conflict() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    legacy_body = {
        "pr_ref": "owner/repo#1",
        "review_key": "k-1",
        "verdict": "needs_review",
        "mode": "shadow",
        "generated_at": "2026-07-07T00:00:00Z",
        "freshness": "fresh",
        "reason_codes": [],
        "metadata": {},
        "findings": [],
    }
    await store.write_state(
        change_review_state_key("k-1"),
        {
            **legacy_body,
            **_PROVENANCE,
            "evidence_digest": evidence_body_digest(legacy_body),
            "revision": 1,
        },
    )

    replay = await ledger.record_change_review(
        _review("k-1", generated_at="2026-07-07T01:00:00+01:00"),
        freshness="fresh",
        **_PROVENANCE,
    )

    assert replay.created is False
    assert replay.conflict is False
    stored = await store.read_state(change_review_state_key("k-1"))
    assert stored is not None
    assert stored["generated_at"] == "2026-07-07T00:00:00Z"
    assert CONFLICT_MARKER_FIELD not in stored


async def test_read_recent_change_reviews_returns_newest_first() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    await ledger.record_change_review(
        _review("k-new", _finding(), generated_at="2026-07-07T02:00:00Z"),
        freshness="fresh",
        **_PROVENANCE,
    )
    await ledger.record_change_review(
        _review("k-old", _finding(), generated_at="2026-07-07T01:00:00Z"),
        freshness="fresh",
        **_PROVENANCE,
    )
    replay = await ledger.record_change_review(
        _review("k-old", _finding(), generated_at="2026-07-07T01:00:00Z"),
        freshness="fresh",
        **_PROVENANCE,
    )

    reviews = await ledger.read_recent_change_reviews(limit=10)
    assert replay.created is False
    assert replay.conflict is False
    assert [row["review_key"] for row in reviews] == ["k-new", "k-old"]
    assert len(store.audit_entries) == 2


async def test_read_latest_posture_report_is_none_when_unrecorded() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    assert await ledger.read_latest_posture_report(_SCOPE) is None


def test_empty_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="scope MUST be non-empty"):
        posture_report_state_key("  ")


def test_empty_review_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="review key MUST be non-empty"):
        change_review_state_key("")


async def test_provenance_identity_is_required() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    with pytest.raises(ValueError, match="activity_id MUST be non-blank"):
        await ledger.record_posture_report(
            _report(),
            freshness="fresh",
            activity_id=" ",
            correlation_id="correlation-1",
            evidence_source_revision="sha256:feedface",
        )
    with pytest.raises(ValueError, match="evidence_source_revision MUST be non-blank"):
        await ledger.record_posture_report(
            _report(),
            freshness="fresh",
            activity_id="activity-1",
            correlation_id="correlation-1",
            evidence_source_revision="",
        )


async def test_read_recent_change_reviews_bounds_limit() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    with pytest.raises(ValueError, match=r"limit MUST be in \[1, 1000\]"):
        await ledger.read_recent_change_reviews(limit=0)


async def test_change_review_key_at_the_bound_is_accepted_and_over_bound_rejected() -> None:
    """256 chars matches the Operator API's detail-lookup bound; 257 does not.

    A key this call accepts MUST always be fetchable through the Operator
    API's list-then-detail round trip; rejecting anything over that same
    bound here, before any write, is what keeps that round trip whole.
    """

    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    accepted = await ledger.record_change_review(
        _review("k" * 256, _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert accepted.created is True
    assert accepted.key == change_review_state_key("k" * 256)

    with pytest.raises(ValueError, match=r"review key MUST be <= 256 characters"):
        await ledger.record_change_review(
            _review("k" * 257, _finding()),
            freshness="fresh",
            **_PROVENANCE,
        )

    # The rejected call never persisted anything under its own identity.
    reviews = await ledger.read_recent_change_reviews(limit=10)
    assert len(reviews) == 1
    assert reviews[0]["review_key"] == "k" * 256


async def test_change_review_findings_at_the_bound_are_accepted_and_over_bound_rejected() -> None:
    """200 findings matches the Operator API's projection bound; 201 does not.

    A row this call persists MUST always be rendered as usable evidence by
    the Operator API's projection, not silently made permanently
    ``evidence_malformed``; rejecting an over-long finding list here,
    before any write or activity publication, is what keeps that promise.
    """

    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    accepted = await ledger.record_change_review(
        _review("k-200", *_findings_batch(200)),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert accepted.created is True

    with pytest.raises(ValueError, match=r"findings MUST number <= 200, got 201"):
        await ledger.record_change_review(
            _review("k-201", *_findings_batch(201)),
            freshness="fresh",
            **_PROVENANCE,
        )

    # The rejected call never persisted a row under its own identity.
    reviews = await ledger.read_recent_change_reviews(limit=10)
    assert [row["review_key"] for row in reviews] == ["k-200"]


async def test_posture_report_findings_at_the_bound_are_accepted_and_over_bound_rejected() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    accepted = await ledger.record_posture_report(
        _report(*_findings_batch(200)),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert accepted.created is True

    with pytest.raises(ValueError, match=r"findings MUST number <= 200, got 201"):
        await ledger.record_posture_report(
            _report(*_findings_batch(201)),
            freshness="fresh",
            **_PROVENANCE,
        )

    # The rejected call never overwrote the accepted latest snapshot.
    report = await ledger.read_latest_posture_report(_SCOPE)
    assert report is not None
    assert len(report["findings"]) == 200


async def test_finding_evidence_refs_at_the_bound_are_accepted_and_over_bound_rejected() -> None:
    """200 evidence_refs matches the projection's ``_MAX_ITEMS``; 201 does not."""

    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    refs_200 = tuple(f"ref-{i}" for i in range(200))
    refs_201 = tuple(f"ref-{i}" for i in range(201))

    accepted = await ledger.record_change_review(
        _review("k-refs-200", _finding(evidence_refs=refs_200)),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert accepted.created is True

    with pytest.raises(ValueError, match=r"finding evidence_refs MUST number <= 200, got 201"):
        await ledger.record_change_review(
            _review("k-refs-201", _finding(evidence_refs=refs_201)),
            freshness="fresh",
            **_PROVENANCE,
        )

    reviews = await ledger.read_recent_change_reviews(limit=10)
    assert [row["review_key"] for row in reviews] == ["k-refs-200"]


async def test_finding_evidence_ref_at_the_char_bound_is_accepted_and_over_bound_rejected() -> None:
    """512 chars matches the projection's ``_MAX_TEXT_LEN``; 513 does not."""

    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    accepted = await ledger.record_change_review(
        _review("k-ref-512", _finding(evidence_refs=("x" * 512,))),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert accepted.created is True

    with pytest.raises(
        ValueError, match=r"finding evidence_refs entries MUST be <= 512 characters"
    ):
        await ledger.record_change_review(
            _review("k-ref-513", _finding(evidence_refs=("x" * 513,))),
            freshness="fresh",
            **_PROVENANCE,
        )


async def test_blank_finding_evidence_ref_is_rejected() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    with pytest.raises(
        ValueError, match=r"finding evidence_refs entries MUST be non-blank strings"
    ):
        await ledger.record_change_review(
            _review("k-blank-ref", _finding(evidence_refs=("  ",))),
            freshness="fresh",
            **_PROVENANCE,
        )


async def test_duplicate_finding_evidence_ref_is_rejected() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    with pytest.raises(ValueError, match=r"finding evidence_refs entries MUST be unique"):
        await ledger.record_change_review(
            _review("k-dup-ref", _finding(evidence_refs=("dup", "dup"))),
            freshness="fresh",
            **_PROVENANCE,
        )


async def test_reason_codes_at_the_bound_are_accepted_and_over_bound_rejected() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    codes_200 = tuple(f"code-{i}" for i in range(200))
    codes_201 = tuple(f"code-{i}" for i in range(201))

    accepted = await ledger.record_change_review(
        _review("k-codes-200", _finding()),
        freshness="unavailable",
        reason_codes=codes_200,
        **_PROVENANCE,
    )
    assert accepted.created is True

    with pytest.raises(ValueError, match=r"reason_codes MUST number <= 200, got 201"):
        await ledger.record_change_review(
            _review("k-codes-201", _finding()),
            freshness="unavailable",
            reason_codes=codes_201,
            **_PROVENANCE,
        )


async def test_blank_reason_code_is_rejected() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    with pytest.raises(ValueError, match=r"reason_codes entries MUST be non-blank strings"):
        await ledger.record_posture_report(
            _report(),
            freshness="unavailable",
            reason_codes=("  ",),
            **_PROVENANCE,
        )


async def test_duplicate_reason_code_is_rejected() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    with pytest.raises(ValueError, match=r"reason_codes entries MUST be unique"):
        await ledger.record_posture_report(
            _report(),
            freshness="unavailable",
            reason_codes=("dup", "dup"),
            **_PROVENANCE,
        )


async def test_evidence_source_revision_at_the_char_bound_is_accepted_and_over_bound_rejected() -> (
    None
):
    """512 chars matches the projection's ``_bounded_identity`` bound; 513 does not."""

    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    accepted = await ledger.record_posture_report(
        _report(),
        freshness="fresh",
        activity_id="activity-1",
        correlation_id="correlation-1",
        evidence_source_revision="r" * 512,
    )
    assert accepted.created is True

    with pytest.raises(ValueError, match=r"evidence_source_revision MUST be <= 512 characters"):
        await ledger.record_posture_report(
            _report(),
            freshness="fresh",
            activity_id="activity-2",
            correlation_id="correlation-2",
            evidence_source_revision="r" * 513,
        )


@pytest.mark.parametrize("field", ["activity_id", "correlation_id"])
async def test_provenance_identity_at_the_char_bound_is_accepted_and_over_bound_rejected(
    field: str,
) -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    accepted_activity_id = "x" * 512 if field == "activity_id" else _PROVENANCE["activity_id"]
    accepted_correlation_id = (
        "x" * 512 if field == "correlation_id" else _PROVENANCE["correlation_id"]
    )

    write = await ledger.record_posture_report(
        _report(),
        freshness="fresh",
        activity_id=accepted_activity_id,
        correlation_id=accepted_correlation_id,
        evidence_source_revision=_PROVENANCE["evidence_source_revision"],
    )
    assert write.created is True

    rejected_activity_id = "x" * 513 if field == "activity_id" else _PROVENANCE["activity_id"]
    rejected_correlation_id = (
        "x" * 513 if field == "correlation_id" else _PROVENANCE["correlation_id"]
    )
    with pytest.raises(ValueError, match=rf"{field} MUST be <= 512 characters"):
        await ledger.record_posture_report(
            _report(),
            freshness="fresh",
            activity_id=rejected_activity_id,
            correlation_id=rejected_correlation_id,
            evidence_source_revision=_PROVENANCE["evidence_source_revision"],
        )


class _StalledCasStateStore:
    """Wrap ``InMemoryStateStore`` to force two CAS attempts to race.

    Nothing in this in-memory store ever suspends mid-call, so two
    concurrently scheduled coroutines never actually interleave unless a
    call explicitly yields. This wrapper makes the *first* arrival at
    ``compare_and_set_state_with_audit`` block until a *second* concurrent
    caller has also reached the same call, so the deterministic scenario
    this exercises is: two conflict-resolution attempts computed against
    the exact same pre-write snapshot, both trying to tombstone the row,
    with only the underlying compare-and-set - not call order - deciding
    the single winner.
    """

    def __init__(self, inner: InMemoryStateStore) -> None:
        self._inner = inner
        self._arrivals = 0
        self._second_arrived: asyncio.Event = asyncio.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Any,
        *,
        expected_revision: int,
        audit_entry: Any,
    ) -> bool:
        self._arrivals += 1
        if self._arrivals == 1:
            await self._second_arrived.wait()
        else:
            self._second_arrived.set()
        return await self._inner.compare_and_set_state_with_audit(
            key, value, expected_revision=expected_revision, audit_entry=audit_entry
        )


class _StalledMatchingReadStateStore:
    """Pause the matching replay's first read until a conflict tombstone lands."""

    def __init__(self, inner: InMemoryStateStore) -> None:
        self._inner = inner
        self._reads = 0
        self._tombstoned: asyncio.Event = asyncio.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def read_state(self, key: str) -> Any:
        self._reads += 1
        captured = await self._inner.read_state(key)
        if self._reads == 1:
            await self._tombstoned.wait()
        return captured

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Any,
        *,
        expected_revision: int,
        audit_entry: Any,
    ) -> bool:
        advanced = await self._inner.compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )
        if advanced:
            self._tombstoned.set()
        return advanced


async def test_concurrent_conflicting_redeliveries_tombstone_exactly_once() -> None:
    """Two different-body redeliveries racing the same tombstone write.

    Both read the identical pre-conflict row, so without a CAS both would
    independently decide to overwrite it with a plain ``write_state`` - a
    lost-update race where the loser's overwrite can silently discard the
    winner's tombstone. With the atomic compare-and-set, exactly one
    concurrent attempt lands; the other loses, re-reads the now-tombstoned
    row, and reports the conflict it observes instead of clobbering it.
    """

    inner = InMemoryStateStore()
    store = _StalledCasStateStore(inner)
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    baseline = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert baseline.created is True

    results = await asyncio.gather(
        ledger.record_change_review(
            _review("k-1", _finding(rule="r-conflict-a"), verdict="blocked"),
            freshness="fresh",
            **_PROVENANCE,
        ),
        ledger.record_change_review(
            _review("k-1", _finding(rule="r-conflict-b"), verdict="blocked"),
            freshness="fresh",
            **_PROVENANCE,
        ),
    )

    # Neither concurrent conflicting redelivery is ever allowed to publish a
    # completed/available result once its identity is contested.
    assert all(result.conflict is True for result in results)
    assert all(result.created is False for result in results)
    assert all(result.stored_evidence_digest == baseline.evidence_digest for result in results)

    # Exactly one durable mutation lands: the compare-and-set audit trail
    # proves the loser re-read instead of racing a second overwrite.
    conflict_audits = [
        entry
        for entry in inner.audit_entries
        if entry["entry"].get("action_kind") == "assurance_twin.review_conflict_marked"
    ]
    assert len(conflict_audits) == 1

    rows = await ledger.read_recent_change_reviews(limit=10)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "needs_review"
    assert rows[0]["findings"][0]["rule_id"] == "r-1"
    marker = rows[0][CONFLICT_MARKER_FIELD]
    assert marker["reason_code"] == REVIEW_CONFLICT_REASON_CODE
    assert marker["stored_evidence_digest"] == baseline.evidence_digest
    # The winning rejected digest is one of the two racers, never a third
    # value and never the baseline's own digest.
    assert marker["rejected_evidence_digest"] in {result.evidence_digest for result in results}


async def test_concurrent_duplicate_conflict_after_tombstone_never_publishes_available() -> None:
    """A duplicate racing the very write that first tombstones its identity.

    Simulates the exact regression this hardens: a redelivery of the
    *same* conflicting body arrives twice, concurrently. Under the old
    read-then-``write_state`` sequence, both racers could observe the
    pre-conflict row and one's plain overwrite could silently replace the
    other's tombstone. With the CAS, only one lands; the loser's retry
    observes the marker its sibling wrote and reports conflict, never a
    completed/available outcome for either racer.
    """

    inner = InMemoryStateStore()
    store = _StalledCasStateStore(inner)
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    baseline = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )

    duplicate_conflicting_review = _review("k-1", _finding(rule="r-2"), verdict="blocked")
    results = await asyncio.gather(
        ledger.record_change_review(
            duplicate_conflicting_review,
            freshness="fresh",
            **_PROVENANCE,
        ),
        ledger.record_change_review(
            duplicate_conflicting_review,
            freshness="fresh",
            **_PROVENANCE,
        ),
    )

    assert all(result.conflict is True for result in results)
    assert {result.evidence_digest for result in results} == {results[0].evidence_digest}
    assert all(result.stored_evidence_digest == baseline.evidence_digest for result in results)

    conflict_audits = [
        entry
        for entry in inner.audit_entries
        if entry["entry"].get("action_kind") == "assurance_twin.review_conflict_marked"
    ]
    assert len(conflict_audits) == 1


async def test_matching_replay_is_read_only_before_a_later_conflict() -> None:
    inner = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=inner)

    baseline = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert baseline.created is True

    matching_result = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert matching_result.conflict is False
    assert matching_result.created is False
    assert matching_result.evidence_digest == baseline.evidence_digest
    assert len(inner.audit_entries) == 1

    conflicting_result = await ledger.record_change_review(
        _review("k-1", _finding(rule="r-conflict"), verdict="blocked"),
        freshness="fresh",
        **_PROVENANCE,
    )
    assert conflicting_result.conflict is True
    assert conflicting_result.created is False
    assert conflicting_result.stored_evidence_digest == baseline.evidence_digest

    conflict_audits = [
        entry
        for entry in inner.audit_entries
        if entry["entry"].get("action_kind") == "assurance_twin.review_conflict_marked"
    ]
    assert len(conflict_audits) == 1

    rows = await ledger.read_recent_change_reviews(limit=10)
    assert len(rows) == 1
    assert rows[0]["findings"][0]["rule_id"] == "r-1"
    marker = rows[0][CONFLICT_MARKER_FIELD]
    assert marker["reason_code"] == REVIEW_CONFLICT_REASON_CODE
    assert marker["stored_evidence_digest"] == baseline.evidence_digest


async def test_concurrent_matching_replay_observes_a_racing_conflict_without_writing() -> None:
    inner = InMemoryStateStore()
    store = _StalledMatchingReadStateStore(inner)
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    baseline = await ledger.record_change_review(
        _review("k-1", _finding()),
        freshness="fresh",
        **_PROVENANCE,
    )

    matching_result, conflicting_result = await asyncio.gather(
        ledger.record_change_review(
            _review("k-1", _finding()),
            freshness="fresh",
            **_PROVENANCE,
        ),
        ledger.record_change_review(
            _review("k-1", _finding(rule="r-conflict"), verdict="blocked"),
            freshness="fresh",
            **_PROVENANCE,
        ),
    )

    assert matching_result.conflict is True
    assert matching_result.created is False
    assert matching_result.evidence_digest == baseline.evidence_digest
    assert matching_result.stored_evidence_digest == baseline.evidence_digest
    assert conflicting_result.conflict is True

    conflict_audits = [
        entry
        for entry in inner.audit_entries
        if entry["entry"].get("action_kind") == "assurance_twin.review_conflict_marked"
    ]
    assert len(conflict_audits) == 1


async def test_concurrent_new_key_writes_preserve_first_writer_and_mark_conflict() -> None:
    """Two brand-new-key writes racing ``write_state_if_absent`` itself.

    The first-writer-wins path was already atomic via the underlying
    ``write_state_if_absent`` primitive; this asserts that guarantee still
    holds end to end through the ledger when both callers race a key that
    has never been written. (No CAS stall is needed here: only the loser
    of ``write_state_if_absent`` ever reaches the compare-and-set path.)
    """

    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)

    results = await asyncio.gather(
        ledger.record_change_review(
            _review("k-new", _finding(rule="r-a")),
            freshness="fresh",
            **_PROVENANCE,
        ),
        ledger.record_change_review(
            _review("k-new", _finding(rule="r-b"), verdict="blocked"),
            freshness="fresh",
            **_PROVENANCE,
        ),
    )

    created_results = [result for result in results if result.created]
    assert len(created_results) == 1
    conflicting = [result for result in results if not result.created]
    assert len(conflicting) == 1
    assert conflicting[0].conflict is True
    assert conflicting[0].stored_evidence_digest == created_results[0].evidence_digest
