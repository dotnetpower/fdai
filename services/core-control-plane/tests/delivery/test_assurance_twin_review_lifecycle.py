"""One current Forseti review per proposal, settled only by the writer's real outcome."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.assurance_twin_evidence_source import AssuranceTwinEvidenceRequestRelay
from fdai.delivery.assurance_twin_publication import AssuranceTwinOutboxPublisher
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_operator_service.assurance_twin_posture_projection import (
    assurance_twin_review_list_projection,
)

from tests.delivery.assurance_twin_review_harness import (
    REVISION_B,
    PublicAccessPolicy,
    TwinHarness,
    proposal,
    reviewed_effect,
    what_if,
)

_REVIEW_PREFIX = "runtime:assurance-twin-review:"


@pytest.fixture
def now() -> datetime:
    """Pin one instant per test; writer admission still compares with the wall clock."""
    return datetime.now(UTC) - timedelta(seconds=1)


async def _listed(twin: TwinHarness) -> dict[str, object]:
    rows, _ = await twin.store.read_state_page(_REVIEW_PREFIX, limit=10)
    keyed = tuple({"key": f"{_REVIEW_PREFIX}{row['review_key']}", "value": row} for row in rows)
    return assurance_twin_review_list_projection(keyed, durable_key_prefix=_REVIEW_PREFIX)


async def test_stricter_generation_supersedes_the_older_clear_review(now: datetime) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    assert await twin.writer.process(await twin.relayed_request(bus))
    assert (await twin.producer.review_pending()).reviewed == 1
    [first] = await twin.ledger.read_recent_change_reviews()
    assert first["verdict"] == "clear"

    twin.evaluator.activate(
        PublicAccessPolicy(denied_values=frozenset({"enabled", "disabled"}), generation="9"),
        generation_time=now - timedelta(seconds=30),
    )
    second = what_if(item, now, observed_at=now - timedelta(seconds=10))
    await twin.intake.submit(proposal=item, what_if=second, correlation_id="c-2")
    assert (await twin.producer.review_pending()).recorded == 1
    assert await twin.writer.process(await twin.relayed_request(bus))

    [current] = await twin.ledger.read_recent_change_reviews()
    assert current["pr_ref"] == item.proposal_ref and current["verdict"] == "blocked"
    listed = await _listed(twin)
    assert listed["available"] is True and listed["complete"] is True
    reviews = listed["reviews"]
    assert isinstance(reviews, list) and [row["verdict"] for row in reviews] == ["blocked"]
    superseded = [
        entry["entry"]
        for entry in twin.store.audit_entries
        if entry["entry"].get("action_kind") == "assurance_twin.review_superseded"
    ]
    assert [entry["superseded_evidence_digest"] for entry in superseded] == [
        first["evidence_digest"]
    ]
    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=twin.ledger, bus=bus)
    assert await publisher.publish_pending() == 1


async def test_delayed_older_review_cannot_replace_the_newer_current_review(
    now: datetime,
) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    older = await twin.relayed_request(bus)
    twin.evaluator.activate(
        PublicAccessPolicy(denied_values=frozenset({"enabled", "disabled"}), generation="9"),
        generation_time=now - timedelta(seconds=30),
    )
    newer_what_if = what_if(item, now, observed_at=now - timedelta(seconds=10))
    await twin.intake.submit(proposal=item, what_if=newer_what_if, correlation_id="c-2")
    summary = await twin.producer.review_pending()
    assert summary.retried == 1 and summary.recorded == 1
    newer = await twin.relayed_request(bus)
    assert await twin.writer.process(newer)

    assert not await twin.writer.process(older)
    [current] = await twin.ledger.read_recent_change_reviews()
    assert current["evidence_source_revision"] == newer.source_revision
    assert current["verdict"] == "blocked"


async def test_intake_is_reviewed_only_after_the_writer_confirms(now: datetime) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    request = await twin.relayed_request(bus)

    waiting = await twin.producer.review_pending()
    assert (waiting.reviewed, waiting.retried, waiting.unavailable) == (0, 0, 0)
    [row] = await twin.intake_rows()
    assert row["status"] == "recorded"
    assert "assurance_twin_proposal_review_reviewed" not in dict(twin.intake_audit())

    assert await twin.writer.process(request)
    assert (await twin.producer.review_pending()).reviewed == 1
    [row] = await twin.intake_rows()
    assert row["status"] == "reviewed"


async def test_inventory_fence_rejection_retires_the_request_and_rederives(
    now: datetime,
) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    stale = await twin.relayed_request(bus)
    twin.inventory.current = REVISION_B

    assert not await twin.writer.process(stale)
    assert (await twin.producer.review_pending()).retried == 1
    [row] = await twin.intake_rows()
    assert (row["status"], row["attempts"], row["reason_code"]) == (
        "pending",
        1,
        "inventory_revision_changed",
    )
    relay = AssuranceTwinEvidenceRequestRelay(repository=twin.repository, bus=bus)
    assert await relay.publish_pending() == 0

    assert (await twin.producer.review_pending()).recorded == 1
    fresh = await twin.relayed_request(bus)
    assert fresh.source_revision != stale.source_revision
    assert await twin.writer.process(fresh)
    assert (await twin.producer.review_pending()).reviewed == 1
    [review] = await twin.ledger.read_recent_change_reviews()
    assert review["metadata"]["inventory_revision"] == REVISION_B
    assert [kind for kind, _ in twin.intake_audit()] == [
        "assurance_twin_proposal_review_submitted",
        "assurance_twin_proposal_review_recorded",
        "assurance_twin_proposal_review_retry",
        "assurance_twin_proposal_review_recorded",
        "assurance_twin_proposal_review_reviewed",
    ]


async def test_generation_fence_rejection_settles_after_the_bounded_attempt(
    now: datetime,
) -> None:
    twin = TwinHarness(now, effects=(reviewed_effect(),), max_derivations=1)
    bus = InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    request = await twin.relayed_request(bus)
    twin.evaluator.activate(
        PublicAccessPolicy(generation="9"),
        generation_time=now - timedelta(seconds=30),
    )

    assert not await twin.writer.process(request)
    assert (await twin.producer.review_pending()).unavailable == 1
    [row] = await twin.intake_rows()
    assert (row["status"], row["reason_code"]) == ("unavailable", "rule_generation_changed")
    assert twin.intake_audit()[-1] == (
        "assurance_twin_proposal_review_unavailable",
        "rule_generation_changed",
    )
    assert "assurance_twin_proposal_review_reviewed" not in dict(twin.intake_audit())
    relay = AssuranceTwinEvidenceRequestRelay(repository=twin.repository, bus=bus)
    assert await relay.publish_pending() == 0
    assert await twin.ledger.read_recent_change_reviews() == ()


async def test_fence_rejection_after_what_if_expiry_settles_the_fence_reason(
    now: datetime,
) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    request = await twin.relayed_request(bus)
    twin.inventory.current = REVISION_B
    assert not await twin.writer.process(request)
    twin.now = now + timedelta(minutes=11)

    assert (await twin.producer.review_pending()).unavailable == 1
    [row] = await twin.intake_rows()
    assert (row["status"], row["reason_code"]) == ("unavailable", "inventory_revision_changed")
    assert row["attempts"] == 0


async def test_inventory_change_during_the_writer_commit_revokes_and_rederives(
    now: datetime,
) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    request = await twin.relayed_request(bus)
    twin.inventory.change_on_read = twin.inventory.reads + 1

    assert not await twin.writer.process(request)
    [revoked] = await twin.ledger.read_recent_change_reviews()
    assert revoked["conflict"] is not None and revoked["publication_outbox"] is None
    assert (await twin.producer.review_pending()).retried == 1
    [row] = await twin.intake_rows()
    assert (row["status"], row["reason_code"]) == ("pending", "inventory_revision_changed")

    assert (await twin.producer.review_pending()).recorded == 1
    assert await twin.writer.process(await twin.relayed_request(bus))
    assert (await twin.producer.review_pending()).reviewed == 1
    [current] = await twin.ledger.read_recent_change_reviews()
    assert "conflict" not in current
    assert current["metadata"]["inventory_revision"] == REVISION_B
    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=twin.ledger, bus=bus)
    assert await publisher.publish_pending() == 1


async def test_generation_change_during_derivation_is_bounded(now: datetime) -> None:
    twin = TwinHarness(now, effects=(reviewed_effect(),), max_derivations=2)
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    twin.evaluator.current = "sha256:" + "f" * 64

    assert (await twin.producer.review_pending()).retried == 1
    assert (await twin.producer.review_pending()).unavailable == 1
    [row] = await twin.intake_rows()
    assert (row["status"], row["reason_code"], row["attempts"]) == (
        "unavailable",
        "rule_generation_changed",
        1,
    )
    assert await twin.evidence_rows() == ()
