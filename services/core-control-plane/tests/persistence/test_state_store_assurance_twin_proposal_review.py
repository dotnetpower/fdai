"""The durable ledger keeps exactly one current typed-proposal review per proposal."""

from __future__ import annotations

from fdai.core.assurance_twin.posture_activity import build_change_review_activity
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    CONFLICT_MARKER_FIELD,
    REVIEW_CONFLICT_REASON_CODE,
    AssuranceTwinLedgerWrite,
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import OperationalFreshness

_PROPOSAL = "action-proposal:" + "a" * 64
_KEY = f"runtime:assurance-twin-review:{_PROPOSAL}"


def _review(generated_at: str, *, verdict: str = "clear") -> IacReview:
    findings = (
        ()
        if verdict == "clear"
        else (
            Finding(
                rule_id="rule.public-access",
                resource=ResourceRef("object-storage", "storage-a"),
                severity="high",
                reason="public access is enabled",
                evidence_refs=("receipt:1",),
            ),
        )
    )
    return IacReview(
        pr_ref=_PROPOSAL,
        review_key=_PROPOSAL,
        findings=findings,
        verdict=verdict,
        mode=Mode.SHADOW,
        generated_at=generated_at,
        metadata={"evidence_kind": "typed_action_proposal"},
    )


async def _record(
    ledger: StateStoreAssuranceTwinPostureLedger,
    review: IacReview,
    *,
    source_revision: str,
) -> AssuranceTwinLedgerWrite:
    activity = build_change_review_activity(
        review, correlation_id="correlation-1", freshness=OperationalFreshness.FRESH
    )
    return await ledger.record_proposal_review(
        review,
        freshness="fresh",
        activity_id=activity.activity_id,
        correlation_id="correlation-1",
        evidence_source_revision=source_revision,
        source_confirmed=True,
        activity=activity,
    )


async def test_newer_revision_supersedes_the_older_review_in_one_transition() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    first = await _record(ledger, _review("2026-09-28T00:00:00+00:00"), source_revision="s-1")
    newer = await _record(
        ledger,
        _review("2026-09-28T00:05:00+00:00", verdict="blocked"),
        source_revision="s-2",
    )

    assert newer.created is True
    assert newer.stored_evidence_digest == first.evidence_digest
    rows = await ledger.read_recent_change_reviews()
    assert len(rows) == 1
    [row] = rows
    assert (row["verdict"], row["evidence_source_revision"], row["revision"]) == (
        "blocked",
        "s-2",
        2,
    )
    assert row["publication_outbox"]["record_revision"] == 2
    assert row["publication_outbox"]["evidence_digest"] == newer.evidence_digest
    superseded = [
        entry["entry"]
        for entry in store.audit_entries
        if entry["entry"]["action_kind"] == "assurance_twin.review_superseded"
    ]
    assert [entry["superseded_evidence_digest"] for entry in superseded] == [first.evidence_digest]
    assert superseded[0]["owner_agent"] == "Saga"
    assert await store.verify_chain()


async def test_delayed_older_revision_and_identical_replay_do_not_write() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    newer = await _record(
        ledger,
        _review("2026-09-28T00:05:00+00:00", verdict="blocked"),
        source_revision="s-2",
    )
    audit_length = len(tuple(store.audit_entries))

    older = await _record(ledger, _review("2026-09-28T00:00:00+00:00"), source_revision="s-1")
    replay = await _record(
        ledger,
        _review("2026-09-28T00:05:00+00:00", verdict="blocked"),
        source_revision="s-2",
    )

    assert older.created is False
    assert older.stored_evidence_digest == newer.evidence_digest
    assert replay.created is False and replay.conflict is False
    assert replay.stored_evidence_digest == replay.evidence_digest
    assert len(tuple(store.audit_entries)) == audit_length
    [row] = await ledger.read_recent_change_reviews()
    assert row["evidence_source_revision"] == "s-2" and row["revision"] == 1


async def test_same_instant_different_review_is_tombstoned_until_a_newer_revision() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    await _record(ledger, _review("2026-09-28T00:00:00+00:00"), source_revision="s-1")
    conflict = await _record(
        ledger,
        _review("2026-09-28T00:00:00+00:00", verdict="blocked"),
        source_revision="s-1b",
    )

    assert conflict.conflict is True
    row = await store.read_state(_KEY)
    assert row is not None
    assert row[CONFLICT_MARKER_FIELD]["reason_code"] == REVIEW_CONFLICT_REASON_CODE
    assert row["publication_outbox"] is None

    newer = await _record(
        ledger,
        _review("2026-09-28T00:05:00+00:00", verdict="blocked"),
        source_revision="s-2",
    )
    assert newer.created is True
    row = await store.read_state(_KEY)
    assert row is not None and CONFLICT_MARKER_FIELD not in row
    assert row["evidence_source_revision"] == "s-2"


async def test_each_review_revision_has_its_own_activity_identity() -> None:
    first = build_change_review_activity(
        _review("2026-09-28T00:00:00+00:00"),
        correlation_id="correlation-1",
        freshness=OperationalFreshness.FRESH,
    )
    newer = build_change_review_activity(
        _review("2026-09-28T00:05:00+00:00", verdict="blocked"),
        correlation_id="correlation-1",
        freshness=OperationalFreshness.FRESH,
    )
    replay = build_change_review_activity(
        _review("2026-09-28T00:00:00+00:00"),
        correlation_id="correlation-1",
        freshness=OperationalFreshness.FRESH,
    )

    assert first.idempotency_key != newer.idempotency_key
    assert replay.idempotency_key == first.idempotency_key
    assert _PROPOSAL not in first.activity_id
