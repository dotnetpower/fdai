"""Assurance Twin durable ledger and unpublished activity-value tests."""

from __future__ import annotations

from fdai.core.assurance_twin import build_posture_assessment_report
from fdai.delivery.assurance_twin_posture import (
    POSTURE_CONFLICT_REASON_CODE,
    REVIEW_CONFLICT_REASON_CODE,
    AssuranceTwinPostureRecorder,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import OperationalFreshness

_SCOPE = "sub/00000000-0000-0000-0000-000000000001"
_TOPIC = "fdai.pipeline.stages"
_REVISION = "sha256:0000000000000000000000000000000000000000000000000000000000000001"


def _finding(rule: str = "r-1", ref: str = "vm-a", severity: str = "high") -> Finding:
    return Finding(
        rule_id=rule,
        resource=ResourceRef(resource_type="compute.vm", ref=ref),
        severity=severity,  # type: ignore[arg-type]
        reason="reason",
    )


def _report(
    *findings: Finding,
    generated_at: str = "2026-07-07T00:00:00Z",
) -> object:
    return build_posture_assessment_report(
        scope=_SCOPE,
        generated_at=generated_at,
        mode=Mode.SHADOW,
        findings=findings,
    )


def _review(key: str = "k-1", *findings: Finding, verdict: str = "needs_review") -> IacReview:
    return IacReview(
        pr_ref="owner/repo#1",
        review_key=key,
        findings=findings,
        verdict=verdict,
        mode=Mode.SHADOW,
        generated_at="2026-07-07T00:00:00Z",
    )


def _recorder(store: InMemoryStateStore) -> AssuranceTwinPostureRecorder:
    return AssuranceTwinPostureRecorder(
        ledger=StateStoreAssuranceTwinPostureLedger(store=store),
    )


async def test_posture_report_is_durably_recorded_without_an_unordered_bus_tip() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    recorder = _recorder(store)

    result = await recorder.record_posture_report(
        _report(_finding()),
        correlation_id="posture-1",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )

    assert result.published is False
    assert result.durable_write_created is True
    assert result.activity.owner_agent == "Heimdall"
    assert result.activity.execution_authority is False

    envelopes = [event async for event in bus.subscribe(_TOPIC, "replay-consumer")]
    assert envelopes == []

    durable = await recorder.read_latest_posture_report(_SCOPE)
    assert durable is not None
    assert durable["verdict"] == "blocked"
    assert durable["activity_id"] == result.activity.activity_id
    assert durable["correlation_id"] == result.activity.correlation_id
    assert durable["evidence_digest"] == result.evidence_digest
    assert durable["evidence_source_revision"] == _REVISION


async def test_change_review_redelivery_is_idempotent_and_never_publishes_a_tip() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    recorder = _recorder(store)

    first = await recorder.record_change_review(
        _review("k-1", _finding()),
        correlation_id="review-1",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )
    second = await recorder.record_change_review(
        _review("k-1", _finding()),
        correlation_id="review-1",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )

    assert first.published is False
    assert second.published is False
    assert first.durable_write_created is True
    assert second.durable_write_created is False
    assert second.conflict is False
    assert second.activity.activity_id == first.activity.activity_id
    reviews = await recorder.read_recent_change_reviews(limit=10)
    assert len(reviews) == 1

    envelopes = [event async for event in bus.subscribe(_TOPIC, "replay-consumer")]
    assert envelopes == [], "change-review activity publication is disabled entirely"


async def test_superseded_posture_report_is_not_published() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    recorder = _recorder(store)

    newer = await recorder.record_posture_report(
        _report(_finding(rule="new"), generated_at="2026-07-07T02:00:00Z"),
        correlation_id="posture-new",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )
    older = await recorder.record_posture_report(
        _report(_finding(rule="old"), generated_at="2026-07-07T01:00:00Z"),
        correlation_id="posture-old",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )

    assert newer.published is False
    assert older.durable_write_created is False
    assert older.published is False
    assert older.activity.status.value == "superseded"
    envelopes = [event async for event in bus.subscribe(_TOPIC, "replay-consumer")]
    assert envelopes == []


async def test_same_timestamp_posture_conflict_is_unavailable_and_unpublished() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    recorder = _recorder(store)

    await recorder.record_posture_report(
        _report(_finding(rule="first")),
        correlation_id="posture-first",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )
    conflict = await recorder.record_posture_report(
        _report(_finding(rule="second")),
        correlation_id="posture-second",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )

    assert conflict.conflict is True
    assert conflict.durable_write_created is False
    assert conflict.published is False
    assert conflict.activity.freshness is OperationalFreshness.UNAVAILABLE
    assert conflict.activity.reason_codes == (POSTURE_CONFLICT_REASON_CODE,)
    assert [event async for event in bus.subscribe(_TOPIC, "replay-consumer")] == []


async def test_conflicting_review_key_stays_durably_unavailable_and_never_publishes() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    recorder = _recorder(store)

    await recorder.record_change_review(
        _review("k-1", _finding()),
        correlation_id="review-1",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )
    conflicting = await recorder.record_change_review(
        _review("k-1", _finding(rule="r-2"), verdict="blocked"),
        correlation_id="review-2",
        freshness=OperationalFreshness.FRESH,
        evidence_source_revision=_REVISION,
    )

    assert conflicting.published is False
    assert conflicting.conflict is True
    assert conflicting.durable_write_created is False
    assert conflicting.activity.freshness is OperationalFreshness.UNAVAILABLE
    assert conflicting.activity.status.value == "failed"
    assert conflicting.activity.reason_codes == (REVIEW_CONFLICT_REASON_CODE,)
    assert conflicting.activity.execution_authority is False

    reviews = await recorder.read_recent_change_reviews(limit=10)
    assert len(reviews) == 1
    assert reviews[0]["verdict"] == "needs_review", "the durable body is never replaced"

    envelopes = [event async for event in bus.subscribe(_TOPIC, "replay-consumer")]
    assert envelopes == [], "change-review activity publication is disabled entirely"


async def test_unavailable_source_never_grants_authority() -> None:
    store = InMemoryStateStore()
    recorder = _recorder(store)

    result = await recorder.record_posture_report(
        _report(),
        correlation_id="posture-2",
        freshness=OperationalFreshness.UNAVAILABLE,
        reason_codes=("inventory_freshness_ttl_exceeded",),
        evidence_source_revision=_REVISION,
    )

    assert result.activity.freshness is OperationalFreshness.UNAVAILABLE
    assert result.activity.execution_authority is False
    assert result.activity.status.value == "failed"
