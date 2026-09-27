"""Exact-revision, authority-free report and review publication."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.assurance_twin import build_posture_assessment_report
from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.assurance_twin_publication import (
    PUBLICATION_TOPIC,
    AssuranceTwinOutboxPublisher,
    AssuranceTwinPublicationEvent,
    _validated_publication,
)
from fdai.delivery.assurance_twin_writers import (
    REQUEST_TOPIC,
    AssuranceTwinAgentWriter,
    AssuranceTwinPublishRequest,
    ProposedIacAssessment,
    RetainedTwinEvidence,
    RuleFindingAssessment,
    findings_digest,
    request_key,
    rule_set_digest,
)
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
    _change_review_body,
    evidence_body_digest,
)
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.event_bus import EventPublishNotAttemptedError
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.assurance_twin_posture_projection import (
    assurance_twin_posture_projection,
    assurance_twin_review_detail_projection,
)
from fdai_service_contracts import OperationalFreshness
from fdai_service_contracts.semantic_turn import LOGICAL_TOPIC_FIELD

_SCOPE = "sub/00000000-0000-0000-0000-000000000001"
_REVISION = "sha256:" + "a" * 64
_NOW = datetime.now(UTC) - timedelta(seconds=1)


def _finding(rule: str = "rule-1") -> Finding:
    return Finding(
        rule_id=rule,
        resource=ResourceRef(resource_type="compute.vm", ref="vm-1"),
        severity="high",
        reason="observed policy mismatch",
        evidence_refs=("receipt:1",),
    )


def _report(rule: str = "rule-1") -> object:
    return build_posture_assessment_report(
        scope=_SCOPE,
        generated_at=_NOW.isoformat(),
        mode=Mode.SHADOW,
        findings=(_finding(rule),),
    )


def _review(rule: str = "rule-1") -> IacReview:
    return IacReview(
        pr_ref="example/project#1",
        review_key="review-1",
        findings=(_finding(rule),),
        verdict="blocked",
        mode=Mode.SHADOW,
        generated_at=_NOW.isoformat(),
    )


def _evidence(record: object) -> RetainedTwinEvidence:
    if isinstance(record, IacReview):
        body = _change_review_body(record, freshness="fresh", reason_codes=())
    else:
        body = {
            **record.to_dict(),  # type: ignore[attr-defined]
            "generated_at": _NOW.isoformat(),
            "freshness": "fresh",
            "reason_codes": [],
        }
    evaluated_rule_ids = tuple(sorted({finding.rule_id for finding in record.findings}))  # type: ignore[attr-defined]
    membership_digest = rule_set_digest(evaluated_rule_ids)
    return RetainedTwinEvidence(
        record=record,  # type: ignore[arg-type]
        source_revision=_REVISION,
        evidence_digest=evidence_body_digest(body),
        fresh_until=datetime.now(UTC) + timedelta(minutes=1),
        coverage_refs=("coverage:1",),
        complete=True,
        rule_assessment=RuleFindingAssessment(
            source_revision=_REVISION,
            rule_set_digest=membership_digest,
            rule_membership_digest=membership_digest,
            rule_generation_digest=membership_digest,
            inventory_revision=_REVISION,
            evaluated_rule_ids=evaluated_rule_ids,
            findings_digest=findings_digest(record.findings),  # type: ignore[attr-defined]
            coverage_refs=(membership_digest, "rule-coverage:1"),
            complete=True,
        ),
        proposed_iac=(
            ProposedIacAssessment(
                source_revision=_REVISION,
                pr_ref=record.pr_ref,
                proposal_digest="sha256:" + "c" * 64,
                evidence_refs=("proposed-change:1",),
                complete=True,
            )
            if isinstance(record, IacReview)
            else None
        ),
    )


class _Source:
    def __init__(self) -> None:
        self.posture: RetainedTwinEvidence | None = _evidence(_report())
        self.review: RetainedTwinEvidence | None = _evidence(_review())

    async def read_posture(self, scope: str, revision: str) -> RetainedTwinEvidence | None:
        return self.posture

    async def read_review(self, review_key: str, revision: str) -> RetainedTwinEvidence | None:
        return self.review


@pytest.mark.parametrize("kind", ["posture", "review"])
@pytest.mark.parametrize(
    "gap",
    [
        "missing",
        "incomplete",
        "wrong_revision",
        "substituted",
        "missing_rules",
        "wrong_rules",
        "missing_coverage",
    ],
)
async def test_rule_assessment_required_for_both_writers(kind: str, gap: str) -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, forseti = _bindings(store, bus, source)
    evidence = source.posture if kind == "posture" else source.review
    assert evidence is not None and evidence.rule_assessment is not None
    rule = evidence.rule_assessment
    changed = {
        "missing": None,
        "incomplete": replace(rule, complete=False),
        "wrong_revision": replace(rule, source_revision="sha256:" + "f" * 64),
        "substituted": replace(rule, findings_digest="sha256:" + "e" * 64),
        "missing_rules": replace(rule, evaluated_rule_ids=()),
        "wrong_rules": replace(rule, evaluated_rule_ids=("other-rule",)),
        "missing_coverage": replace(rule, coverage_refs=()),
    }[gap]
    if kind == "posture":
        source.posture = replace(evidence, rule_assessment=changed)
    else:
        source.review = replace(evidence, rule_assessment=changed)
    assert not await (heimdall if kind == "posture" else forseti).process(_request(kind))
    assert await ledger.pending_publications(owner="Heimdall") == ()
    assert await ledger.pending_publications(owner="Forseti") == ()
    assert store.audit_entries == ()


@pytest.mark.parametrize("gap", ["missing", "incomplete", "wrong_revision", "wrong_pr", "no_refs"])
async def test_review_requires_complete_proposed_iac_evidence(gap: str) -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, _, forseti = _bindings(store, bus, source)
    assert source.review is not None and source.review.proposed_iac is not None
    proposal = source.review.proposed_iac
    changed = {
        "missing": None,
        "incomplete": replace(proposal, complete=False),
        "wrong_revision": replace(proposal, source_revision="sha256:" + "f" * 64),
        "wrong_pr": replace(proposal, pr_ref="other-pr"),
        "no_refs": replace(proposal, evidence_refs=()),
    }[gap]
    source.review = replace(source.review, proposed_iac=changed)
    assert not await forseti.process(_request("review"))
    assert await ledger.pending_publications(owner="Forseti") == ()
    assert store.audit_entries == ()


async def test_malformed_source_proof_and_forged_request_fail_closed() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, _ = _bindings(store, bus, source)
    assert source.posture is not None and source.posture.rule_assessment is not None
    source.posture = replace(
        source.posture,
        rule_assessment=replace(
            source.posture.rule_assessment,
            coverage_refs=(None,),  # type: ignore[arg-type]
        ),
    )
    assert not await heimdall.process(_request("posture"))
    assert not await heimdall.process(
        _request("posture").model_copy(update={"idempotency_key": "forged"})
    )
    assert await ledger.pending_publications(owner="Heimdall") == ()
    assert store.audit_entries == ()


async def test_zero_findings_is_clear_only_after_complete_rule_assessment() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, _ = _bindings(store, bus, source)
    clear = build_posture_assessment_report(
        scope=_SCOPE, generated_at=_NOW.isoformat(), mode=Mode.SHADOW, findings=()
    )
    assert source.posture is not None and source.posture.rule_assessment is not None
    source.posture = replace(
        source.posture,
        record=clear,
        evidence_digest=evidence_body_digest(
            {
                **clear.to_dict(),
                "generated_at": _NOW.isoformat(),
                "freshness": "fresh",
                "reason_codes": [],
            }
        ),
        rule_assessment=replace(
            source.posture.rule_assessment,
            findings_digest=findings_digest(clear.findings),
        ),
    )
    assert await heimdall.process(_request("posture"))
    row = await ledger.read_latest_posture_report(_SCOPE)
    assert row is not None and row["verdict"] == "clear"
    source.posture = replace(
        source.posture, rule_assessment=replace(source.posture.rule_assessment, complete=False)
    )
    assert not await heimdall.process(_request("posture"))


def _request(kind: str) -> AssuranceTwinPublishRequest:
    key = _SCOPE if kind == "posture" else "review-1"
    return AssuranceTwinPublishRequest(
        kind=kind,  # type: ignore[arg-type]
        source_key=key,
        source_revision=_REVISION,
        correlation_id=f"correlation-{kind}",
        idempotency_key=request_key(kind, key, _REVISION),
    )


def _bindings(
    store: InMemoryStateStore, bus: InMemoryEventBus, source: _Source
) -> tuple[
    StateStoreAssuranceTwinPostureLedger,
    AssuranceTwinAgentWriter,
    AssuranceTwinAgentWriter,
]:
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    recorder = AssuranceTwinPostureRecorder(ledger=ledger)
    return (
        ledger,
        AssuranceTwinAgentWriter(owner="Heimdall", source=source, recorder=recorder),
        AssuranceTwinAgentWriter(owner="Forseti", source=source, recorder=recorder),
    )


async def test_independent_writers_stage_exact_owned_records_audit_and_outbox() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, forseti = _bindings(store, bus, source)
    assert await heimdall.process(_request("posture"))
    assert await forseti.process(_request("review"))
    assert not await heimdall.process(_request("review"))
    assert not await forseti.process(_request("posture"))

    for owner in ("Heimdall", "Forseti"):
        rows = await ledger.pending_publications(owner=owner)
        assert len(rows) == 1
        _, row = rows[0]
        outbox = row["publication_outbox"]
        assert outbox["record_revision"] == row["revision"] == 1
        assert outbox["evidence_digest"] == row["evidence_digest"]
        assert outbox["owner_agent"] == owner
        assert outbox["activity"]["execution_authority"] is False
    assert len(store.audit_entries) == 2
    assert [entry["entry"]["owner_agent"] for entry in store.audit_entries] == ["Saga", "Saga"]
    assert await store.verify_chain()
    assert [event async for event in bus.subscribe(PUBLICATION_TOPIC, "no-write-publish")] == []
    posture = await ledger.read_latest_posture_report(_SCOPE)
    review = (await ledger.read_recent_change_reviews())[0]
    assert posture is not None
    projected = assurance_twin_posture_projection(
        ({"key": f"runtime:assurance-twin-posture:{_SCOPE}", "value": posture},)
    )
    assert projected["available"] is True, projected["gaps"]
    detail = assurance_twin_review_detail_projection(
        {"value": review}, requested_review_key="review-1"
    )
    assert detail is not None and detail["available"] is True


async def test_restart_replays_pending_and_duplicates_do_not_append_or_publish_again() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, forseti = _bindings(store, bus, source)
    assert await heimdall.process(_request("posture"))
    assert await forseti.process(_request("review"))
    assert await heimdall.process(_request("posture"))
    assert await forseti.process(_request("review"))
    assert len(store.audit_entries) == 2
    for owner in ("Heimdall", "Forseti"):
        relay = AssuranceTwinOutboxPublisher(
            owner=owner,
            ledger=StateStoreAssuranceTwinPostureLedger(store=store),
            bus=bus,
        )
        assert await relay.publish_pending() == 1
        assert await relay.publish_pending() == 0
        assert await ledger.pending_publications(owner=owner) == ()
    events = [e async for e in bus.subscribe(PUBLICATION_TOPIC, "twin-reader")]
    assert len(events) == 2
    assert {e.payload["owner_agent"] for e in events} == {"Heimdall", "Forseti"}
    for envelope in events:
        validated = AssuranceTwinPublicationEvent.model_validate(envelope.payload)
        assert validated.record_revision == 1
        assert validated.evidence_source_revision == _REVISION
        assert validated.current is False
        assert validated.publication_complete is False
        assert validated.execution_authority is False
        assert validated.activity.execution_authority is False
    assert await store.verify_chain()
    assert len(store.audit_entries) == 4
    posture = await ledger.read_latest_posture_report(_SCOPE)
    assert posture is not None
    assert (
        assurance_twin_posture_projection(
            ({"key": f"runtime:assurance-twin-posture:{_SCOPE}", "value": posture},)
        )["available"]
        is True
    )


class _FailsOnceBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    async def publish(self, topic: str, key: str, payload: object) -> object:
        if self.fail:
            self.fail = False
            raise EventPublishNotAttemptedError("offline")
        return await super().publish(topic, key, payload)  # type: ignore[arg-type]


async def test_broker_failure_preserves_outbox_without_claiming_publication() -> None:
    store, bus, source = InMemoryStateStore(), _FailsOnceBus(), _Source()
    ledger, heimdall, _ = _bindings(store, bus, source)
    assert await heimdall.process(_request("posture"))
    relay = AssuranceTwinOutboxPublisher(owner="Heimdall", ledger=ledger, bus=bus)
    assert await relay.publish_pending() == 0
    assert len(await ledger.pending_publications(owner="Heimdall")) == 1
    assert await relay.publish_pending() == 1
    assert len(store.audit_entries) == 2


@pytest.mark.parametrize(
    "issue", ["missing", "incomplete", "stale", "conflict", "revision", "digest", "verdict"]
)
async def test_unavailable_evidence_never_generates_a_review(issue: str) -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, _, forseti = _bindings(store, bus, source)
    assert source.review is not None
    changes = {
        "missing": None,
        "incomplete": replace(source.review, complete=False),
        "stale": replace(source.review, fresh_until=datetime.now(UTC) - timedelta(seconds=1)),
        "conflict": replace(source.review, conflict=True),
        "revision": replace(source.review, source_revision="sha256:" + "b" * 64),
        "digest": replace(source.review, evidence_digest="sha256:" + "b" * 64),
        "verdict": _evidence(replace(source.review.record, verdict="clear")),
    }
    source.review = changes[issue]
    assert not await forseti.process(_request("review"))
    assert await ledger.pending_publications(owner="Forseti") == ()
    if issue == "conflict":
        assert store.audit_entries[-1]["entry"]["action_kind"] == (
            "assurance_twin.source_conflict_marked"
        )
        retained = await store.read_state("runtime:assurance-twin-review:review-1")
        assert retained is not None
        assert retained["conflict"]["reason_code"] == "assurance_twin_review_key_conflict"
    else:
        assert store.audit_entries == ()


async def test_old_report_cannot_be_refreshed_by_a_new_expiry_stamp() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, _ = _bindings(store, bus, source)
    old = build_posture_assessment_report(
        scope=_SCOPE,
        generated_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        mode=Mode.SHADOW,
        findings=(_finding(),),
    )
    assert source.posture is not None
    source.posture = replace(
        source.posture,
        record=old,
        evidence_digest=evidence_body_digest(
            {
                **old.to_dict(),
                "generated_at": old.generated_at,
                "freshness": "fresh",
                "reason_codes": [],
            }
        ),
    )
    assert not await heimdall.process(_request("posture"))
    assert await ledger.pending_publications(owner="Heimdall") == ()


async def test_conflict_tombstone_suppresses_pending_exact_review() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, _, forseti = _bindings(store, bus, source)
    assert await forseti.process(_request("review"))
    source.review = _evidence(_review("different-rule"))
    assert not await forseti.process(_request("review"))
    assert await ledger.pending_publications(owner="Forseti") == ()
    assert (
        await AssuranceTwinOutboxPublisher(
            owner="Forseti", ledger=ledger, bus=bus
        ).publish_pending()
        == 0
    )
    rows = await ledger.read_recent_change_reviews()
    assert rows[0]["conflict"]
    assert [e async for e in bus.subscribe(PUBLICATION_TOPIC, "reader")] == []


async def test_newer_posture_supersedes_older_pending_revision() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, _ = _bindings(store, bus, source)
    assert await heimdall.process(_request("posture"))
    assert source.posture is not None
    newer = build_posture_assessment_report(
        scope=_SCOPE,
        generated_at=(_NOW + timedelta(milliseconds=1)).isoformat(),
        mode=Mode.SHADOW,
        findings=(_finding("new-rule"),),
    )
    newer_body = {
        **newer.to_dict(),
        "generated_at": newer.generated_at,
        "freshness": "fresh",
        "reason_codes": [],
    }
    assert source.posture.rule_assessment is not None
    source.posture = replace(
        source.posture,
        record=newer,
        evidence_digest=evidence_body_digest(newer_body),
        rule_assessment=replace(
            source.posture.rule_assessment,
            evaluated_rule_ids=("new-rule",),
            rule_set_digest=rule_set_digest(("new-rule",)),
            rule_membership_digest=rule_set_digest(("new-rule",)),
            rule_generation_digest=rule_set_digest(("new-rule",)),
            findings_digest=findings_digest(newer.findings),
            coverage_refs=(rule_set_digest(("new-rule",)), "rule-coverage:1"),
        ),
    )
    assert await heimdall.process(_request("posture"))
    row_key, row = (await ledger.pending_publications(owner="Heimdall"))[0]
    assert row["revision"] == row["publication_outbox"]["record_revision"] == 2
    assert _validated_publication(row, owner="Heimdall", key=row_key) is not None
    assert (
        await AssuranceTwinOutboxPublisher(
            owner="Heimdall", ledger=ledger, bus=bus
        ).publish_pending()
        == 1
    )
    events = [e async for e in bus.subscribe(PUBLICATION_TOPIC, "reader")]
    assert len(events) == 1
    assert events[0].payload["record_revision"] == 2


async def test_raced_posture_publish_cannot_claim_current_or_ack_old_revision() -> None:
    store, source = InMemoryStateStore(), _Source()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    recorder = AssuranceTwinPostureRecorder(ledger=ledger)
    writer = AssuranceTwinAgentWriter(owner="Heimdall", source=source, recorder=recorder)
    assert await writer.process(_request("posture"))

    class _AdvancingBus(InMemoryEventBus):
        advanced = False

        async def publish(self, topic: str, key: str, payload: object) -> object:
            if not self.advanced:
                self.advanced = True
                newer = build_posture_assessment_report(
                    scope=_SCOPE,
                    generated_at=(_NOW + timedelta(milliseconds=1)).isoformat(),
                    mode=Mode.SHADOW,
                    findings=(_finding("newer-rule"),),
                )
                await recorder.record_posture_report(
                    newer,
                    correlation_id="newer-correlation",
                    freshness=OperationalFreshness.FRESH,
                    evidence_source_revision=_REVISION,
                )
            return await super().publish(topic, key, payload)  # type: ignore[arg-type]

    bus = _AdvancingBus()
    relay = AssuranceTwinOutboxPublisher(owner="Heimdall", ledger=ledger, bus=bus)
    assert await relay.publish_pending() == 0
    old_event = [e async for e in bus.subscribe(PUBLICATION_TOPIC, "reader")][0]
    assert old_event.payload["record_revision"] == 1
    assert old_event.payload["current"] is False
    assert old_event.payload["publication_complete"] is False
    assert (await ledger.read_latest_posture_report(_SCOPE))["revision"] == 2
    assert await relay.publish_pending() == 1


async def test_substituted_outbox_is_rejected_before_bus_publish() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, _ = _bindings(store, bus, source)
    assert await heimdall.process(_request("posture"))
    key, row = (await ledger.pending_publications(owner="Heimdall"))[0]
    await store.write_state(
        key, {**row, "publication_outbox": {**row["publication_outbox"], "record_revision": 99}}
    )
    with pytest.raises(RuntimeError, match="exact retained revision"):
        await AssuranceTwinOutboxPublisher(
            owner="Heimdall", ledger=ledger, bus=bus
        ).publish_pending()
    assert [e async for e in bus.subscribe(PUBLICATION_TOPIC, "reader")] == []


class _BrokenAuditStore(InMemoryStateStore):
    broken = True

    def _append_audit_locked(self, entry: object) -> None:
        if self.broken:
            raise RuntimeError("audit unavailable")
        super()._append_audit_locked(entry)  # type: ignore[arg-type]


async def test_audit_failure_rolls_back_record_and_outbox_atomically() -> None:
    store, bus, source = _BrokenAuditStore(), InMemoryEventBus(), _Source()
    ledger, heimdall, _ = _bindings(store, bus, source)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await heimdall.process(_request("posture"))
    assert await ledger.read_latest_posture_report(_SCOPE) is None
    assert await ledger.pending_publications(owner="Heimdall") == ()
    assert store.audit_entries == ()


async def test_audit_failure_rolls_back_revision_advance_atomically() -> None:
    store, bus, source = _BrokenAuditStore(), InMemoryEventBus(), _Source()
    store.broken = False
    ledger, heimdall, _ = _bindings(store, bus, source)
    assert await heimdall.process(_request("posture"))
    initial = await ledger.read_latest_posture_report(_SCOPE)
    audit_count = len(store.audit_entries)
    newer = build_posture_assessment_report(
        scope=_SCOPE,
        generated_at=(_NOW + timedelta(milliseconds=1)).isoformat(),
        mode=Mode.SHADOW,
        findings=(_finding("new-rule"),),
    )
    assert source.posture is not None
    assert source.posture.rule_assessment is not None
    source.posture = replace(
        source.posture,
        record=newer,
        rule_assessment=replace(
            source.posture.rule_assessment,
            evaluated_rule_ids=("new-rule",),
            rule_set_digest=rule_set_digest(("new-rule",)),
            rule_membership_digest=rule_set_digest(("new-rule",)),
            rule_generation_digest=rule_set_digest(("new-rule",)),
            findings_digest=findings_digest(newer.findings),
            coverage_refs=(rule_set_digest(("new-rule",)), "rule-coverage:1"),
        ),
        evidence_digest=evidence_body_digest(
            {
                **newer.to_dict(),
                "generated_at": newer.generated_at,
                "freshness": "fresh",
                "reason_codes": [],
            }
        ),
    )
    store.broken = True
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await heimdall.process(_request("posture"))
    assert await ledger.read_latest_posture_report(_SCOPE) == initial
    assert len(store.audit_entries) == audit_count


async def test_source_requests_are_schema_checked_before_retained_reads() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    _, heimdall, _ = _bindings(store, bus, source)
    request = _request("posture")
    await bus.publish(REQUEST_TOPIC, request.idempotency_key, request.model_dump(mode="json"))
    await bus.publish(REQUEST_TOPIC, "wrong-key", request.model_dump(mode="json"))
    await bus.publish(REQUEST_TOPIC, "malformed", {"unknown": "data"})
    stop = asyncio.Event()
    task = asyncio.create_task(heimdall.run(bus, stop))
    await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert len(store.audit_entries) == 1
    assert len([e async for e in bus.subscribe(f"{REQUEST_TOPIC}.dlq", "reader")]) == 2


async def test_source_unavailable_request_is_explicitly_dead_lettered() -> None:
    store, bus, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    source.review = None
    _, _, forseti = _bindings(store, bus, source)
    request = _request("review")
    await bus.publish(REQUEST_TOPIC, request.idempotency_key, request.model_dump(mode="json"))
    stop = asyncio.Event()
    task = asyncio.create_task(forseti.run(bus, stop))
    await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    gaps = [e async for e in bus.subscribe(f"{REQUEST_TOPIC}.dlq", "reader")]
    assert len(gaps) == 1 and gaps[0].payload["reason"] == "evidence_unavailable"
    assert store.audit_entries == ()
    assert [e async for e in bus.subscribe(PUBLICATION_TOPIC, "reader")] == []


async def test_runtime_logical_bus_carries_both_twin_boundaries() -> None:
    assert {REQUEST_TOPIC, PUBLICATION_TOPIC} <= RUNTIME_LOGICAL_TOPICS
    store, physical, source = InMemoryStateStore(), InMemoryEventBus(), _Source()
    bus = MultiplexedEventBus(
        bus=physical, logical_topics=RUNTIME_LOGICAL_TOPICS, physical_topic="shared-events"
    )
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    writer = AssuranceTwinAgentWriter(
        owner="Forseti", source=source, recorder=AssuranceTwinPostureRecorder(ledger=ledger)
    )
    request = _request("review")
    await bus.publish(REQUEST_TOPIC, request.idempotency_key, request.model_dump(mode="json"))
    stop = asyncio.Event()
    task = asyncio.create_task(writer.run(bus, stop))
    await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert (
        await AssuranceTwinOutboxPublisher(
            owner="Forseti", ledger=ledger, bus=bus
        ).publish_pending()
        == 1
    )
    physical_events = [e async for e in physical.subscribe("shared-events", "physical-reader")]
    assert len(physical_events) == 2
    assert {e.payload[LOGICAL_TOPIC_FIELD] for e in physical_events} == {
        REQUEST_TOPIC,
        PUBLICATION_TOPIC,
    }
    publication = [e async for e in bus.subscribe(PUBLICATION_TOPIC, "twin-reader")]
    assert len(publication) == 1
    assert AssuranceTwinPublicationEvent.model_validate(publication[0].payload).owner_agent == (
        "Forseti"
    )
