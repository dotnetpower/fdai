"""The Twin outbox relay stays bounded by unpublished rows, not retained history."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.core.assurance_twin import build_posture_assessment_report
from fdai.core.assurance_twin.posture_activity import (
    build_change_review_activity,
    build_posture_report_activity,
)
from fdai.delivery.assurance_twin_publication import (
    PUBLICATION_TOPIC,
    AssuranceTwinOutboxPublisher,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import OperationalFreshness

REVIEW_PREFIX = "runtime:assurance-twin-review:"
POSTURE_PREFIX = "runtime:assurance-twin-posture:"
_GENERATED_AT = "2026-09-28T01:00:00+00:00"


class CountingStore(InMemoryStateStore):
    """Count page reads so a relay pass proves its bounded cost."""

    def __init__(self) -> None:
        super().__init__()
        self.page_rows = 0

    async def read_state_page(
        self,
        prefix: str,
        *,
        limit: int,
        offset: int = 0,
        field: str | None = None,
        value: str | None = None,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        rows, total = await super().read_state_page(
            prefix, limit=limit, offset=offset, field=field, value=value
        )
        self.page_rows += len(rows)
        return rows, total


def proposal_ref(index: int) -> str:
    return f"action-proposal:{index:064x}"


async def write_retained_history(store: StateStore, *, published: int, base: int = 0) -> None:
    """Write confirmed published reviews, tombstones, and orphaned provisional rows."""

    for index in range(base, base + published):
        ref = proposal_ref(index)
        tombstone = index % 50 == 0
        orphan = index % 211 == 0
        await store.write_state(
            f"{REVIEW_PREFIX}{ref}",
            {
                "review_key": ref,
                "pr_ref": ref,
                "revision": 2,
                "source_confirmed": not orphan,
                "publication_outbox": (
                    None if tombstone else {"published": orphan is False, "record_revision": 2}
                ),
                **({"conflict": {"reason_code": "tombstone"}} if tombstone else {}),
            },
        )


async def record_pending_review(ledger: StateStoreAssuranceTwinPostureLedger, index: int) -> str:
    """Record one confirmed pending review through the real ledger path."""

    ref = proposal_ref(index)
    review = IacReview(
        pr_ref=ref,
        review_key=ref,
        findings=(),
        verdict="clear",
        mode=Mode.SHADOW,
        generated_at=_GENERATED_AT,
        metadata={"evidence_kind": "typed_action_proposal"},
    )
    activity = build_change_review_activity(
        review, correlation_id=f"correlation-{index}", freshness=OperationalFreshness.FRESH
    )
    await ledger.record_proposal_review(
        review,
        freshness="fresh",
        activity_id=activity.activity_id,
        correlation_id=f"correlation-{index}",
        evidence_source_revision=f"source-{index}",
        source_confirmed=True,
        activity=activity,
    )
    return f"{REVIEW_PREFIX}{ref}"


async def drain(publisher: AssuranceTwinOutboxPublisher, *, passes: int) -> int:
    published = 0
    for _pass in range(passes):
        published += await publisher.publish_pending()
    return published


async def test_pending_reviews_publish_beside_more_than_1000_retained_reviews() -> None:
    store, bus = CountingStore(), InMemoryEventBus()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    await write_retained_history(store, published=1_200)
    pending = [await record_pending_review(ledger, 5_000 + index) for index in range(3)]
    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=ledger, bus=bus)

    store.page_rows = 0
    assert await publisher.publish_pending() == 3
    assert store.page_rows <= 100
    assert await publisher.publish_pending() == 0

    events = [item async for item in bus.subscribe(PUBLICATION_TOPIC, "reader")]
    activity_ids: list[str] = []
    for key in pending:
        row = await store.read_state(key)
        assert row is not None and row["publication_outbox"]["published"] is True
        activity_ids.append(row["activity_id"])
    assert sorted(event.payload["activity"]["activity_id"] for event in events) == sorted(
        activity_ids
    )


async def test_row_without_source_confirmation_field_still_publishes() -> None:
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    await write_retained_history(store, published=1_050)
    key = await record_pending_review(ledger, 9_000)
    row = await store.read_state(key)
    assert row is not None
    await store.write_state(
        key, {field: item for field, item in row.items() if field != "source_confirmed"}
    )
    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=ledger, bus=bus)

    assert await drain(publisher, passes=2) == 1
    published = await store.read_state(key)
    assert published is not None and published["publication_outbox"]["published"] is True


async def test_backlog_beyond_one_page_rotates_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    for index in range(130):
        await record_pending_review(ledger, index)
    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=ledger, bus=bus)

    with caplog.at_level(logging.WARNING):
        first = await publisher.publish_pending()
    assert first == 100
    assert "assurance_twin_outbox_backlog" in caplog.text
    assert first + await drain(publisher, passes=2) == 130


async def test_unconfirmed_rows_do_not_hide_a_confirmed_candidate_for_long() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    confirmed = await record_pending_review(ledger, 1)
    for index in range(100):
        await store.write_state(
            f"{REVIEW_PREFIX}{proposal_ref(10 + index)}",
            {
                "review_key": proposal_ref(10 + index),
                "source_confirmed": False,
                "publication_outbox": {"published": False, "record_revision": 1},
            },
        )

    first = await ledger.pending_publications(owner="Forseti")
    second = await ledger.pending_publications(owner="Forseti")

    assert [key for key, _ in (*first, *second)] == [confirmed]


async def test_heimdall_posture_publication_is_unchanged() -> None:
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    publisher = AssuranceTwinOutboxPublisher(owner="Heimdall", ledger=ledger, bus=bus)
    key = f"{POSTURE_PREFIX}scope-a"

    for generated_at in (_GENERATED_AT, "2026-09-28T01:05:00+00:00"):
        report = build_posture_assessment_report(
            scope="scope-a", generated_at=generated_at, mode=Mode.SHADOW, findings=()
        )
        activity = build_posture_report_activity(
            report, correlation_id="posture", freshness=OperationalFreshness.FRESH
        )
        await ledger.record_posture_report(
            report,
            freshness="fresh",
            activity_id=activity.activity_id,
            correlation_id="posture",
            evidence_source_revision=f"source-{generated_at}",
            source_confirmed=True,
            activity=activity,
        )
        assert await publisher.publish_pending() == 1
        assert await publisher.publish_pending() == 0
        row = await store.read_state(key)
        assert row is not None and row["publication_outbox"]["published"] is True
    assert len([event async for event in bus.subscribe(PUBLICATION_TOPIC, "reader")]) == 2
