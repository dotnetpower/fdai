from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai.delivery.assurance_twin_evidence_source import (
    AssuranceTwinEvidenceExpiredError,
    AssuranceTwinEvidenceRequestRelay,
    StateStoreTwinEvidenceRepository,
)
from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.assurance_twin_publication import AssuranceTwinOutboxPublisher
from fdai.delivery.assurance_twin_writers import (
    REQUEST_TOPIC,
    AssuranceTwinAgentWriter,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REVISION = "sha256:" + "a" * 64
_RULE_SET_REVISION = "sha256:" + "b" * 64
_RULE_GENERATION_REVISION = "sha256:" + "c" * 64
_NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _evidence_clock() -> None:
    """Anchor evidence times at each test's start, not at module import.

    The writers compare freshness against the wall clock, so a module-level instant made every
    test fail once a long shard ran them more than five minutes after collection.
    """
    global _NOW
    _NOW = datetime.now(UTC)


def _finding() -> Finding:
    return Finding(
        rule_id="rule.example",
        resource=ResourceRef("azure.storage-account", "resource-1"),
        severity="high",
        reason="Example policy denied the retained resource.",
        evidence_refs=("rule-evaluation:1",),
    )


async def test_posture_evidence_relay_drives_heimdall_writer() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    relay = AssuranceTwinEvidenceRequestRelay(repository=source, bus=bus)
    assert await relay.publish_pending() == 1
    replay = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-retry",
    )
    assert replay == request
    assert await relay.publish_pending() == 1
    envelopes = [item async for item in bus.subscribe(REQUEST_TOPIC, "writer")]
    assert len(envelopes) == 2
    assert {envelope.key for envelope in envelopes} == {request.idempotency_key}
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(request)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained["verdict"] == "blocked"
    assert retained["publication_outbox"]["owner_agent"] == "Heimdall"
    assert await relay.publish_pending() == 0
    evidence = await store.read_state(
        "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    )
    assert evidence is not None and evidence["request_status"] == "published"


async def test_empty_findings_require_positive_complete_rule_coverage() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)

    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    snapshot = await source.read_posture("scope-1", _REVISION)
    assert snapshot is not None
    assert snapshot.record.verdict.value == "clear"
    assert snapshot.rule_assessment is not None
    assert snapshot.rule_assessment.evaluated_rule_ids == ("rule.example",)
    assert request.kind == "posture"

    with pytest.raises(ValueError, match="incomplete"):
        await source.record_posture(
            scope="scope-2",
            source_revision=_REVISION,
            findings=(),
            evaluated_rule_ids=(),
            coverage_refs=("rule-coverage:1",),
            generated_at=_NOW,
            fresh_until=_NOW + timedelta(minutes=5),
            correlation_id="correlation-2",
        )


async def test_legacy_pending_rule_provenance_is_terminal_not_retried() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    key = "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    retained = await store.read_state(key)
    assert retained is not None
    assessment = dict(retained["rule_assessment"])
    assessment.pop("rule_membership_digest")
    assessment.pop("rule_generation_digest")
    await store.write_state(key, {**dict(retained), "rule_assessment": assessment})

    relay = AssuranceTwinEvidenceRequestRelay(repository=source, bus=bus)
    assert await relay.publish_pending() == 0
    terminal = await store.read_state(key)
    assert terminal is not None and terminal["request_status"] == "conflict"
    assert [item async for item in bus.subscribe(REQUEST_TOPIC, "writer")] == []


async def test_expired_monotonic_candidate_does_not_advance_clock() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    fresh_until = _NOW + timedelta(microseconds=1)
    await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "1" * 64,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=fresh_until,
        correlation_id="first",
    )
    clocks = await store.read_states(
        "runtime:assurance-twin-evidence:clock:",
        limit=10,
    )
    assert len(clocks) == 1 and clocks[0]["revision"] == 2

    with pytest.raises(AssuranceTwinEvidenceExpiredError, match="exceeds freshness"):
        await source.record_posture(
            scope="scope-1",
            source_revision="sha256:" + "2" * 64,
            findings=(),
            evaluated_rule_ids=("rule.example",),
            coverage_refs=("rule-coverage:2",),
            generated_at=_NOW,
            fresh_until=fresh_until,
            correlation_id="second",
        )

    retained_clocks = await store.read_states(
        "runtime:assurance-twin-evidence:clock:",
        limit=10,
    )
    assert retained_clocks == clocks


async def test_failed_source_reservations_spill_without_losing_first_seen_time() -> None:
    class _FailingSourceStore(InMemoryStateStore):
        fail_source_writes = True

        async def write_state_with_audit_if_absent(
            self,
            key,
            value,
            audit_entry,
        ):  # type: ignore[no-untyped-def]
            if (
                self.fail_source_writes
                and key.startswith("runtime:assurance-twin-evidence:")
                and ":clock" not in key
            ):
                raise psycopg.OperationalError("source write unavailable")
            return await super().write_state_with_audit_if_absent(
                key,
                value,
                audit_entry,
            )

    store = _FailingSourceStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    revisions = tuple(f"sha256:{index:064x}" for index in range(1, 131))
    for revision in revisions:
        with pytest.raises(psycopg.OperationalError):
            await source.record_posture(
                scope="scope-1",
                source_revision=revision,
                findings=(),
                evaluated_rule_ids=("rule.example",),
                coverage_refs=("rule-coverage:1",),
                generated_at=_NOW,
                fresh_until=_NOW + timedelta(minutes=5),
                correlation_id=revision,
            )

    archived = await store.read_states(
        "runtime:assurance-twin-evidence:clock-reservation:",
        limit=10,
    )
    assert archived
    store.fail_source_writes = False
    request = await source.record_posture(
        scope="scope-1",
        source_revision=revisions[0],
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW + timedelta(seconds=1),
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="retry",
    )
    retained = await source.read_posture(request.source_key, request.source_revision)
    assert retained is not None
    assert retained.record.generated_at == _NOW.isoformat()


async def test_review_requires_exact_proposed_iac_evidence() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    with pytest.raises(ValueError, match="proposed IaC"):
        await source.record_review(
            review_key="review-1",
            pr_ref="example/repo#1",
            source_revision=_REVISION,
            findings=(_finding(),),
            evaluated_rule_ids=("rule.example",),
            rule_coverage_refs=("rule-coverage:1",),
            rule_set_revision=_RULE_SET_REVISION,
            rule_generation_revision=_RULE_GENERATION_REVISION,
            proposal_digest="",
            proposal_evidence_refs=(),
            generated_at=_NOW,
            fresh_until=_NOW + timedelta(minutes=5),
            correlation_id="correlation-1",
        )

    request = await source.record_review(
        review_key="review-1",
        pr_ref="example/repo#1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        rule_coverage_refs=("rule-coverage:1",),
        rule_set_revision=_RULE_SET_REVISION,
        rule_generation_revision=_RULE_GENERATION_REVISION,
        proposal_digest="sha256:" + "b" * 64,
        proposal_evidence_refs=("proposal-readback:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    snapshot = await source.read_review("review-1", _REVISION)
    assert snapshot is not None
    assert snapshot.proposed_iac is not None
    assert snapshot.proposed_iac.pr_ref == "example/repo#1"
    assert request.kind == "review"
    writer = AssuranceTwinAgentWriter(
        owner="Forseti",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(request)
    retained = await store.read_state("runtime:assurance-twin-review:review-1")
    assert retained is not None
    assert retained["publication_outbox"]["owner_agent"] == "Forseti"


async def test_conflicting_evidence_is_tombstoned_by_accountable_writer() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    values = {
        "scope": "scope-1",
        "source_revision": _REVISION,
        "findings": (_finding(),),
        "evaluated_rule_ids": ("rule.example",),
        "coverage_refs": ("rule-coverage:1",),
        "generated_at": _NOW,
        "fresh_until": _NOW + timedelta(minutes=5),
        "correlation_id": "correlation-1",
    }
    request = await source.record_posture(**values)
    with pytest.raises(ValueError, match="identity conflict"):
        await source.record_posture(
            **{
                **values,
                "findings": (),
            }
        )
    records = await store.read_states("runtime:assurance-twin-evidence:", limit=10)
    evidence = next(record for record in records if "request_status" in record)
    assert evidence["request_status"] == "conflict"
    assert evidence["conflict"] is True
    relay = AssuranceTwinEvidenceRequestRelay(repository=source, bus=bus)
    assert await relay.publish_pending() == 0
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert not await writer.process(request)
    target = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert target is None
    assert await relay.publish_pending() == 0
    records = await store.read_states("runtime:assurance-twin-evidence:", limit=10)
    evidence = next(record for record in records if "request_status" in record)
    assert evidence["request_status"] == "conflict"


async def test_tampered_durable_findings_fail_at_writer_admission() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    key = "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    retained = await store.read_state(key)
    assert retained is not None
    record = dict(retained["record"])
    record["findings"] = []
    await store.write_state(key, {**retained, "record": record})
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )

    assert not await writer.process(request)
    assert await store.read_state("runtime:assurance-twin-posture:scope-1") is None


async def test_oversized_finding_set_is_rejected_before_outbox_write() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    with pytest.raises(ValueError, match="findings MUST number <= 200"):
        await source.record_posture(
            scope="scope-1",
            source_revision=_REVISION,
            findings=tuple(_finding() for _ in range(201)),
            evaluated_rule_ids=("rule.example",),
            coverage_refs=("rule-coverage:1",),
            generated_at=_NOW,
            fresh_until=_NOW + timedelta(minutes=5),
            correlation_id="correlation-1",
        )
    assert await store.read_states("runtime:assurance-twin-evidence:", limit=10) == ()


async def test_request_transport_failure_remains_pending_for_retry() -> None:
    class _FailOnceBus(InMemoryEventBus):
        failed = False

        async def publish(self, topic, key, payload):  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise OSError("broker unavailable")
            return await super().publish(topic, key, payload)

    store = InMemoryStateStore()
    bus = _FailOnceBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    relay = AssuranceTwinEvidenceRequestRelay(repository=source, bus=bus)

    assert await relay.publish_pending() == 0
    assert await relay.publish_pending() == 1
    records = await store.read_states("runtime:assurance-twin-evidence:", limit=10)
    evidence = next(record for record in records if "request_status" in record)
    assert evidence["request_status"] == "pending"


async def test_large_backlog_returns_one_bounded_drain_batch() -> None:
    class _BacklogStore:
        async def read_state_page(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return tuple({} for _ in range(1_000)), 1_001

    source = StateStoreTwinEvidenceRepository(
        store=_BacklogStore(),  # type: ignore[arg-type]
    )

    records, total = await source.pending_requests()
    assert len(records) == 1_000
    assert total == 1_001


async def test_writer_completion_requires_exact_evidence_digest() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    await store.write_state(
        "runtime:assurance-twin-posture:scope-1",
        {
            "evidence_source_revision": _REVISION,
            "evidence_digest": "sha256:" + "f" * 64,
            "conflict": None,
        },
    )

    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=bus,
        ).publish_pending()
        == 1
    )
    retained = await store.read_state(
        "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    )
    assert retained is not None and retained["request_status"] == "pending"


async def test_relay_cursor_reaches_requests_beyond_full_pending_page() -> None:
    class _PagedRepository:
        offsets: list[int] = []

        async def pending_requests(self, *, offset: int = 0):  # type: ignore[no-untyped-def]
            self.offsets.append(offset)
            count = 1_000 if offset == 0 else 1
            rows = tuple(
                {
                    "revision": 1,
                    "request": {
                        "schema_version": "1.0.0",
                        "kind": "posture",
                        "source_key": f"scope-{offset + index}",
                        "source_revision": _REVISION,
                        "correlation_id": "correlation",
                        "idempotency_key": "sha256:" + f"{offset + index + 1:064x}",
                    },
                }
                for index in range(count)
            )
            return rows, 1_001

        async def writer_disposition(self, _request):  # type: ignore[no-untyped-def]
            return "pending"

        async def mark_request_published(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("uncompleted request MUST remain pending")

    repository = _PagedRepository()
    relay = AssuranceTwinEvidenceRequestRelay(
        repository=repository,  # type: ignore[arg-type]
        bus=InMemoryEventBus(),
    )

    assert await relay.publish_pending() == 1_000
    assert await relay.publish_pending() == 1
    assert repository.offsets == [0, 1_000]


async def test_newer_writer_result_retires_older_pending_request() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    older = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "1" * 64,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW - timedelta(seconds=1),
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="older",
    )
    newer = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "2" * 64,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:2",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="newer",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(newer)

    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=bus,
        ).publish_pending()
        == 0
    )
    older_source = await store.read_state(
        "runtime:assurance-twin-evidence:" + older.idempotency_key.removeprefix("sha256:")
    )
    assert older_source is not None
    assert older_source["request_status"] == "superseded"
    assert [item async for item in bus.subscribe(REQUEST_TOPIC, "writer")] == []


async def test_conflicting_source_marks_existing_writer_row_unavailable() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    values = {
        "scope": "scope-1",
        "source_revision": _REVISION,
        "evaluated_rule_ids": ("rule.example",),
        "coverage_refs": ("rule-coverage:1",),
        "generated_at": _NOW,
        "fresh_until": _NOW + timedelta(minutes=5),
        "correlation_id": "correlation-1",
    }
    first = await source.record_posture(findings=(), **values)
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(first)

    with pytest.raises(ValueError, match="identity conflict"):
        await source.record_posture(
            findings=(_finding(),),
            **values,
        )
    assert (
        await AssuranceTwinOutboxPublisher(
            owner="Heimdall",
            ledger=StateStoreAssuranceTwinPostureLedger(store=store),
            bus=InMemoryEventBus(),
        ).publish_pending()
        == 0
    )
    assert not await writer.process(first)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained["conflict"]["reason_code"] == "assurance_twin_posture_timestamp_conflict"
    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=InMemoryEventBus(),
        ).publish_pending()
        == 0
    )
    first_source = await store.read_state(
        "runtime:assurance-twin-evidence:" + first.idempotency_key.removeprefix("sha256:")
    )
    assert first_source is not None
    assert first_source["request_status"] == "conflict"


async def test_equal_time_different_revision_gets_monotonic_generation_time() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    first = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "1" * 64,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="first",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(first)
    second = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "2" * 64,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:2",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="second",
    )

    assert await writer.process(second)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained["evidence_source_revision"] == second.source_revision
    assert retained.get("conflict") is None
    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=InMemoryEventBus(),
        ).publish_pending()
        == 0
    )
    first_source = await store.read_state(
        "runtime:assurance-twin-evidence:" + first.idempotency_key.removeprefix("sha256:")
    )
    assert first_source is not None
    assert first_source["request_status"] == "superseded"


async def test_expired_evidence_is_terminal_without_publication() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW - timedelta(minutes=31),
        fresh_until=_NOW - timedelta(minutes=1),
        correlation_id="expired",
    )

    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=bus,
        ).publish_pending()
        == 0
    )
    retained = await store.read_state(
        "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    )
    assert retained is not None
    assert retained["request_status"] == "expired"
    assert [item async for item in bus.subscribe(REQUEST_TOPIC, "writer")] == []


async def test_superseded_source_cannot_be_written_or_confirmed() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    assert await source.mark_inventory_superseded(request)
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )

    assert not await writer.process(request)
    assert not await source.confirm_writer(
        request,
        evidence_digest="sha256:" + "f" * 64,
    )
    assert await store.read_state("runtime:assurance-twin-posture:scope-1") is None


async def test_inventory_conflict_retries_after_target_revision_race() -> None:
    class _TargetRaceStore(InMemoryStateStore):
        race = False

        async def conflict_assurance_twin_source(
            self,
            *,
            target_key,
            expected_target_revision,
            **kwargs,
        ):  # type: ignore[no-untyped-def]
            if self.race:
                self.race = False
                target = await self.read_state(target_key)
                assert target is not None and expected_target_revision is not None
                await self.compare_and_set_state_with_audit(
                    target_key,
                    {
                        **dict(target),
                        "revision": expected_target_revision + 1,
                    },
                    expected_revision=expected_target_revision,
                    audit_entry={"kind": "synthetic_target_revision_race"},
                )
                return False
            return await super().conflict_assurance_twin_source(
                target_key=target_key,
                expected_target_revision=expected_target_revision,
                **kwargs,
            )

    store = _TargetRaceStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(request)
    store.race = True

    assert await source.mark_inventory_changed(request)
    retained_source = await store.read_state(
        "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    )
    target = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained_source is not None and retained_source["conflict"] is True
    assert target is not None
    assert target["publication_outbox"] is None
    assert target["conflict"]["reason_code"] == "assurance_twin_inventory_revision_changed"


async def test_expired_newer_source_does_not_replay_against_older_tombstone() -> None:
    store = InMemoryStateStore()
    recorder = AssuranceTwinPostureRecorder(
        ledger=StateStoreAssuranceTwinPostureLedger(store=store)
    )
    assert await recorder.mark_source_conflict(
        owner="Heimdall",
        source_key="scope-1",
        generated_at=(_NOW - timedelta(minutes=2)).isoformat(),
        source_revision="sha256:" + "1" * 64,
        rejected_evidence_digest="sha256:" + "f" * 64,
        correlation_id="older",
    )
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "2" * 64,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:2",),
        generated_at=_NOW - timedelta(minutes=1),
        fresh_until=_NOW - timedelta(seconds=1),
        correlation_id="expired",
    )

    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=InMemoryEventBus(),
        ).publish_pending()
        == 0
    )
    retained = await store.read_state(
        "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    )
    assert retained is not None
    assert retained["request_status"] == "expired"


async def test_inflight_writer_rechecks_source_conflict_before_success() -> None:
    class _DelayedRecorder:
        def __init__(self, delegate: AssuranceTwinPostureRecorder) -> None:
            self.delegate = delegate
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def record_posture_report(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.entered.set()
            await self.release.wait()
            return await self.delegate.record_posture_report(*args, **kwargs)

        async def mark_source_conflict(self, **kwargs):  # type: ignore[no-untyped-def]
            return await self.delegate.mark_source_conflict(**kwargs)

    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="initial",
    )
    recorder = _DelayedRecorder(
        AssuranceTwinPostureRecorder(ledger=StateStoreAssuranceTwinPostureLedger(store=store))
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=recorder,  # type: ignore[arg-type]
    )
    task = asyncio.create_task(writer.process(request))
    await recorder.entered.wait()
    with pytest.raises(ValueError, match="identity conflict"):
        await source.record_posture(
            scope="scope-1",
            source_revision=_REVISION,
            findings=(_finding(),),
            evaluated_rule_ids=("rule.example",),
            coverage_refs=("rule-coverage:1",),
            generated_at=_NOW,
            fresh_until=_NOW + timedelta(minutes=5),
            correlation_id="conflict",
        )
    recorder.release.set()

    assert not await task
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained["conflict"]["reason_code"] == "assurance_twin_posture_timestamp_conflict"


async def test_expired_source_conflict_still_tombstones_existing_projection() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="initial",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(request)
    with pytest.raises(ValueError, match="identity conflict"):
        await source.record_posture(
            scope="scope-1",
            source_revision=_REVISION,
            findings=(_finding(),),
            evaluated_rule_ids=("rule.example",),
            coverage_refs=("rule-coverage:1",),
            generated_at=_NOW,
            fresh_until=_NOW + timedelta(minutes=5),
            correlation_id="conflict",
        )
    source_key = "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix(
        "sha256:"
    )
    retained_source = await store.read_state(source_key)
    assert retained_source is not None
    await store.write_state(
        source_key,
        {
            **retained_source,
            "fresh_until": (_NOW - timedelta(minutes=1)).isoformat(),
        },
    )
    relay = AssuranceTwinEvidenceRequestRelay(repository=source, bus=bus)

    assert await relay.publish_pending() == 0
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None and retained["conflict"] is not None
    retained_source = await store.read_state(source_key)
    assert retained_source is not None
    assert retained_source["request_status"] == "conflict"


async def test_older_source_conflict_preserves_newer_projection() -> None:
    store = InMemoryStateStore()
    recorder = AssuranceTwinPostureRecorder(
        ledger=StateStoreAssuranceTwinPostureLedger(store=store)
    )
    newer = await StateStoreTwinEvidenceRepository(store=store).record_posture(
        scope="scope-1",
        source_revision="sha256:" + "2" * 64,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:2",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="newer",
    )
    source = StateStoreTwinEvidenceRepository(store=store)
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=recorder,
    )
    assert await writer.process(newer)

    assert not await recorder.mark_source_conflict(
        owner="Heimdall",
        source_key="scope-1",
        generated_at=(_NOW - timedelta(minutes=1)).isoformat(),
        source_revision="sha256:" + "1" * 64,
        rejected_evidence_digest="sha256:" + "f" * 64,
        correlation_id="older",
    )
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained.get("conflict") is None
    assert retained["evidence_source_revision"] == newer.source_revision


async def test_newer_generation_advances_past_older_conflict_tombstone() -> None:
    store = InMemoryStateStore()
    recorder = AssuranceTwinPostureRecorder(
        ledger=StateStoreAssuranceTwinPostureLedger(store=store)
    )
    assert await recorder.mark_source_conflict(
        owner="Heimdall",
        source_key="scope-1",
        generated_at=(_NOW - timedelta(minutes=1)).isoformat(),
        source_revision="sha256:" + "1" * 64,
        rejected_evidence_digest="sha256:" + "f" * 64,
        correlation_id="older",
    )
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "2" * 64,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:2",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="newer",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=recorder,
    )

    assert await writer.process(request)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained.get("conflict") is None
    assert retained["evidence_source_revision"] == request.source_revision


async def test_transient_confirmation_read_failure_remains_retryable() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    request = await repository.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )

    class _FailSecondRead:
        calls = 0

        async def read_posture(self, scope: str, revision: str):
            self.calls += 1
            if self.calls == 2:
                raise OSError("temporary readback outage")
            return await repository.read_posture(scope, revision)

        async def read_review(self, review_key: str, revision: str):
            return await repository.read_review(review_key, revision)

        async def confirm_writer(self, request, *, evidence_digest):  # type: ignore[no-untyped-def]
            return await repository.confirm_writer(
                request,
                evidence_digest=evidence_digest,
            )

    source = _FailSecondRead()
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )

    assert not await writer.process(request)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None and retained.get("conflict") is None
    assert retained["source_confirmed"] is False
    assert (
        await AssuranceTwinOutboxPublisher(
            owner="Heimdall",
            ledger=StateStoreAssuranceTwinPostureLedger(store=store),
            bus=InMemoryEventBus(),
        ).publish_pending()
        == 0
    )
    assert await writer.process(request)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None and retained["source_confirmed"] is True


async def test_transient_confirmation_write_failure_remains_retryable() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    request = await repository.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )

    class _FailConfirmOnce:
        failed = False

        async def read_posture(self, scope: str, revision: str):
            return await repository.read_posture(scope, revision)

        async def read_review(self, review_key: str, revision: str):
            return await repository.read_review(review_key, revision)

        async def confirm_writer(self, request, *, evidence_digest):  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise OSError("temporary confirmation outage")
            return await repository.confirm_writer(
                request,
                evidence_digest=evidence_digest,
            )

    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=_FailConfirmOnce(),  # type: ignore[arg-type]
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )

    assert not await writer.process(request)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None and retained["source_confirmed"] is False
    assert await writer.process(request)


async def test_source_conflict_retries_after_request_status_race() -> None:
    class _RaceStore(InMemoryStateStore):
        raced = False

        async def compare_and_set_state_with_audit(
            self,
            key,
            value,
            *,
            expected_revision,
            audit_entry,
        ):  # type: ignore[no-untyped-def]
            if value.get("conflict") is True and not self.raced:
                self.raced = True
                current = await self.read_state(key)
                assert current is not None
                await super().compare_and_set_state_with_audit(
                    key,
                    {
                        **current,
                        "revision": expected_revision + 1,
                        "request_status": "published",
                    },
                    expected_revision=expected_revision,
                    audit_entry={"kind": "synthetic_request_status_race"},
                )
                return False
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    store = _RaceStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    values = {
        "scope": "scope-1",
        "source_revision": _REVISION,
        "evaluated_rule_ids": ("rule.example",),
        "coverage_refs": ("rule-coverage:1",),
        "generated_at": _NOW,
        "fresh_until": _NOW + timedelta(minutes=5),
        "correlation_id": "correlation-1",
    }
    await source.record_posture(findings=(), **values)

    with pytest.raises(ValueError, match="identity conflict"):
        await source.record_posture(findings=(_finding(),), **values)
    records = await store.read_states("runtime:assurance-twin-evidence:", limit=10)
    retained = next(record for record in records if "request_status" in record)
    assert retained["conflict"] is True
    assert retained["request_status"] == "conflict"


async def test_evidence_expiring_during_writer_work_stays_provisional() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    request = await repository.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )

    class _ExpireBeforeConfirm:
        async def read_posture(self, scope: str, revision: str):
            return await repository.read_posture(scope, revision)

        async def read_review(self, review_key: str, revision: str):
            return await repository.read_review(review_key, revision)

        async def confirm_writer(self, request, *, evidence_digest):  # type: ignore[no-untyped-def]
            key = "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix(
                "sha256:"
            )
            retained = await store.read_state(key)
            assert retained is not None
            await store.write_state(
                key,
                {
                    **retained,
                    "fresh_until": (_NOW - timedelta(seconds=1)).isoformat(),
                },
            )
            return await repository.confirm_writer(
                request,
                evidence_digest=evidence_digest,
            )

    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=_ExpireBeforeConfirm(),  # type: ignore[arg-type]
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )

    assert not await writer.process(request)
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained["source_confirmed"] is False


async def test_provisional_rows_do_not_hide_confirmed_outbox_candidate() -> None:
    store = InMemoryStateStore()
    prefix = "runtime:assurance-twin-posture:"
    await store.write_state(
        prefix + "confirmed",
        {
            "scope": "confirmed",
            "source_confirmed": True,
            "publication_outbox": {"published": False},
        },
    )
    for index in range(100):
        await store.write_state(
            prefix + f"provisional-{index}",
            {
                "scope": f"provisional-{index}",
                "source_confirmed": False,
                "publication_outbox": {"published": False},
            },
        )

    candidates = await StateStoreAssuranceTwinPostureLedger(store=store).pending_publications(
        owner="Heimdall"
    )
    assert len(candidates) == 1
    assert candidates[0][0] == prefix + "confirmed"


async def test_provisional_rows_do_not_hide_legacy_outbox_candidate() -> None:
    store = InMemoryStateStore()
    prefix = "runtime:assurance-twin-posture:"
    await store.write_state(
        prefix + "legacy",
        {
            "scope": "legacy",
            "publication_outbox": {"published": False},
        },
    )
    for index in range(1_000):
        await store.write_state(
            prefix + f"provisional-{index}",
            {
                "scope": f"provisional-{index}",
                "source_confirmed": False,
                "publication_outbox": {"published": False},
            },
        )

    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    candidates = ()
    for _attempt in range(11):
        candidates = await ledger.pending_publications(owner="Heimdall")
        if any(key == prefix + "legacy" for key, _row in candidates):
            break
    assert any(key == prefix + "legacy" for key, _row in candidates)


async def test_confirmed_batch_reserves_capacity_for_legacy_candidate() -> None:
    store = InMemoryStateStore()
    prefix = "runtime:assurance-twin-posture:"
    await store.write_state(
        prefix + "legacy",
        {
            "scope": "legacy",
            "publication_outbox": {"published": False},
        },
    )
    for index in range(100):
        await store.write_state(
            prefix + f"confirmed-{index}",
            {
                "scope": f"confirmed-{index}",
                "source_confirmed": True,
                "publication_outbox": {"published": False},
            },
        )

    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    await ledger.pending_publications(owner="Heimdall")
    candidates = await ledger.pending_publications(owner="Heimdall")
    assert len(candidates) == 100
    assert any(key == prefix + "legacy" for key, _row in candidates)


async def test_request_publication_is_guarded_against_target_tombstone() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="correlation-1",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(request)
    source_key = "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix(
        "sha256:"
    )
    retained_source = await store.read_state(source_key)
    target_key = "runtime:assurance-twin-posture:scope-1"
    target = await store.read_state(target_key)
    assert retained_source is not None and target is not None
    await store.write_state(
        target_key,
        {
            **target,
            "revision": target["revision"] + 1,
            "conflict": {
                "reason_code": "assurance_twin_posture_timestamp_conflict",
            },
        },
    )

    assert not await source.mark_request_published(
        request,
        expected_revision=retained_source["revision"],
    )
    retained_source = await store.read_state(source_key)
    assert retained_source is not None
    assert retained_source["request_status"] == "pending"


async def test_newer_source_conflict_advances_older_tombstone_generation() -> None:
    store = InMemoryStateStore()
    recorder = AssuranceTwinPostureRecorder(
        ledger=StateStoreAssuranceTwinPostureLedger(store=store)
    )
    assert await recorder.mark_source_conflict(
        owner="Heimdall",
        source_key="scope-1",
        generated_at=(_NOW - timedelta(minutes=1)).isoformat(),
        source_revision="sha256:" + "1" * 64,
        rejected_evidence_digest="sha256:" + "e" * 64,
        correlation_id="older",
    )
    assert await recorder.mark_source_conflict(
        owner="Heimdall",
        source_key="scope-1",
        generated_at=_NOW.isoformat(),
        source_revision="sha256:" + "2" * 64,
        rejected_evidence_digest="sha256:" + "f" * 64,
        correlation_id="newer",
    )
    retained = await store.read_state("runtime:assurance-twin-posture:scope-1")
    assert retained is not None
    assert retained["generated_at"] == _NOW.isoformat()
    assert retained["evidence_source_revision"] == "sha256:" + "2" * 64


async def test_older_conflicted_request_is_superseded_by_newer_clean_target() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    older = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "1" * 64,
        findings=(),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW - timedelta(minutes=1),
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="older",
    )
    with pytest.raises(ValueError, match="identity conflict"):
        await source.record_posture(
            scope="scope-1",
            source_revision=older.source_revision,
            findings=(_finding(),),
            evaluated_rule_ids=("rule.example",),
            coverage_refs=("rule-coverage:1",),
            generated_at=_NOW - timedelta(minutes=1),
            fresh_until=_NOW + timedelta(minutes=5),
            correlation_id="older-conflict",
        )
    newer = await source.record_posture(
        scope="scope-1",
        source_revision="sha256:" + "2" * 64,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:2",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="newer",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(newer)

    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=InMemoryEventBus(),
        ).publish_pending()
        == 0
    )
    retained = await store.read_state(
        "runtime:assurance-twin-evidence:" + older.idempotency_key.removeprefix("sha256:")
    )
    assert retained is not None
    assert retained["request_status"] == "conflict"


async def test_confirmed_writer_result_stays_published_after_source_expiry() -> None:
    store = InMemoryStateStore()
    source = StateStoreTwinEvidenceRepository(store=store)
    request = await source.record_posture(
        scope="scope-1",
        source_revision=_REVISION,
        findings=(_finding(),),
        evaluated_rule_ids=("rule.example",),
        coverage_refs=("rule-coverage:1",),
        generated_at=_NOW,
        fresh_until=_NOW + timedelta(minutes=5),
        correlation_id="confirmed",
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=source,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
    )
    assert await writer.process(request)
    key = "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    retained = await store.read_state(key)
    assert retained is not None
    await store.write_state(
        key,
        {
            **retained,
            "fresh_until": (_NOW - timedelta(minutes=1)).isoformat(),
        },
    )

    assert (
        await AssuranceTwinEvidenceRequestRelay(
            repository=source,
            bus=InMemoryEventBus(),
        ).publish_pending()
        == 0
    )
    retained = await store.read_state(key)
    assert retained is not None
    assert retained["request_status"] == "published"
