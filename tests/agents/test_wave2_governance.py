"""Wave 2 governance staff behavior tests."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.adapters import AuditChainError, InMemoryAuditChain
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga, compute_fingerprint

# ---------------------------------------------------------------------------
# Saga - audit chain + issue dedup
# ---------------------------------------------------------------------------


def test_saga_audit_chain_appends_hash_linked_entries() -> None:
    saga = Saga()
    asyncio.run(
        saga.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "correlation_id": "corr-1",
                "risk_verdict": "auto",
            },
        )
    )
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "producer_principal": "Thor",
                "correlation_id": "corr-1",
                "state": "succeeded",
            },
        )
    )
    assert len(saga.audit_chain.entries) == 2
    saga.audit_chain.verify()


def test_saga_seals_document_admission_as_audit_entry() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    saga.bind_bus(bus)

    asyncio.run(
        saga.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "kind": "document_ingestion",
                "stage": "received",
                "decision": "admit",
                "reason": "ingress_validated",
                "correlation_id": "upload-1",
                "idempotency_key": "document.received:version-1",
                "document_id": "doc-1",
                "upload_id": "upload-1",
            },
        )
    )

    entry = bus.messages_on("object.audit-entry")[0].payload
    assert entry["producer_principal"] == "Saga"
    assert entry["audited_topic"] == "object.verdict"
    assert entry["kind"] == "document_ingestion"
    assert entry["stage"] == "received"
    assert entry["decision"] == "admit"
    assert "record" not in entry


def test_saga_seals_document_human_approval() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    saga.bind_bus(bus)

    asyncio.run(
        saga.on_typed_message(
            "object.approval",
            {
                "producer_principal": "Var",
                "kind": "document_ingestion",
                "stage": "protection_check",
                "state": "approved",
                "correlation_id": "upload-hil",
                "document_id": "doc-hil",
                "upload_id": "upload-hil",
                "approvers": ["reviewer@example.com"],
                "idempotency_key": "document.inspected:version-hil",
            },
        )
    )

    entry = bus.messages_on("object.audit-entry")[0].payload
    assert entry["audited_topic"] == "object.approval"
    assert entry["decision"] == "approved"
    assert entry["approvers"] == ["reviewer@example.com"]
    assert entry["idempotency_key"] == "document.inspected:version-hil"


def test_saga_audit_chain_detects_tamper() -> None:
    chain = InMemoryAuditChain()
    chain.append(principal="Thor", topic="object.action-run", correlation_id="c", payload={})
    chain.append(principal="Thor", topic="object.action-run", correlation_id="c", payload={})
    # Tamper: mutate a payload_digest in place (frozen dataclass -> replace via list)
    tampered = chain.entries[1]
    chain.entries[1] = tampered.__class__(
        seq=tampered.seq,
        prev_hash=tampered.prev_hash,
        entry_hash=tampered.entry_hash,
        principal=tampered.principal,
        topic=tampered.topic,
        correlation_id=tampered.correlation_id,
        payload_digest="deadbeef",
    )
    with pytest.raises(AuditChainError):
        chain.verify()


def test_saga_issue_dedup_creates_once_and_appends_comment_on_repeat() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="cost_query_failed",
        resource_type="storage_account",
        normalized_selector="public_network_field",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )
    first = asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="corr-1",
        )
    )
    second = asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="corr-2",
        )
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["issue_number"] == first["issue_number"]
    assert second["occurrence_count"] == 2
    # Muninn index reflects the count
    idx = saga.state_store.get("issue_fingerprint_index", fp)
    assert idx is not None
    assert idx["occurrence_count"] == 2


def test_saga_close_issue_records_promoting_pr() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="x",
        resource_type="y",
        normalized_selector="z",
        primary_agent="Bragi",
        failure_reason_code="low_confidence",
    )
    asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Bragi",
            intent_category="x",
            failure_reason_code="low_confidence",
            correlation_id="corr-close",
        )
    )
    saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/42")
    issue = saga.github.issues[fp]
    assert issue.open is False
    assert issue.closed_by_pr == "https://example.invalid/pr/42"


def test_saga_replay_returns_ordered_slice_for_correlation() -> None:
    saga = Saga()
    for i in range(3):
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"producer_principal": "Thor", "correlation_id": "keep", "seq": i},
            )
        )
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {"producer_principal": "Thor", "correlation_id": "other", "seq": 99},
        )
    )
    slice_entries = saga.replay_for_correlation("keep")
    assert len(slice_entries) == 3
    assert [e.correlation_id for e in slice_entries] == ["keep"] * 3


def test_saga_escalate_renders_context_lines_in_issue_body() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="cost_query_failed",
        resource_type="storage_account",
        normalized_selector="sel",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )
    asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="corr-ctx",
            context={"resource_id": "vm-9", "region": "koreacentral"},
        )
    )
    body = saga.github.issues[fp].body
    # Context items are rendered as sorted bullet lines in the issue body.
    assert "- region: koreacentral" in body
    assert "- resource_id: vm-9" in body


def test_saga_introspect_scoped_and_general() -> None:
    saga = Saga()
    for i in range(2):
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"producer_principal": "Thor", "correlation_id": "keep", "seq": i},
            )
        )

    # Naming a known correlation id scopes the answer to its entries.
    scoped = asyncio.run(saga.introspect("what happened for keep?", {}))
    assert scoped.facts["correlation_id"] == "keep"
    assert len(scoped.facts["matched_entries"]) == 2
    assert "Thor" in scoped.answer

    # No correlation named -> a general "latest entry" summary.
    general = asyncio.run(saga.introspect("give me an audit overview", {}))
    assert general.facts["audit_entries"] == 2
    assert "latest" in general.answer


def test_saga_introspect_empty_chain() -> None:
    saga = Saga()
    result = asyncio.run(saga.introspect("anything recorded?", {}))
    assert result.facts["audit_entries"] == 0
    assert "empty" in result.answer


# ---------------------------------------------------------------------------
# Muninn - context store
# ---------------------------------------------------------------------------


def test_muninn_indexes_conversation_turns() -> None:
    muninn = Muninn()
    asyncio.run(
        muninn.on_typed_message(
            "object.turn",
            {"turn_id": "t1", "question": "hi", "answer": "hello"},
        )
    )
    stored = muninn.get_context("conversation_turns", "t1")
    assert stored is not None
    assert stored["question"] == "hi"


def test_muninn_requests_index_after_saga_sealed_document_admit() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    muninn = Muninn()
    muninn.bind_bus(bus)

    asyncio.run(
        muninn.on_typed_message(
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.verdict",
                "stage": "protection_check",
                "decision": "admit",
                "correlation_id": "upload-1",
                "idempotency_key": "document.inspected:version-1",
                "document_id": "doc-1",
                "upload_id": "upload-1",
            },
        )
    )

    command = bus.messages_on("object.context-index")[0].payload
    assert command["producer_principal"] == "Muninn"
    assert command["kind"] == "document_ingestion"
    assert command["stage"] == "indexing"
    assert command["command"] == "index"
    assert command["upload_id"] == "upload-1"


def test_muninn_does_not_index_held_or_incomplete_documents() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    muninn = Muninn()
    muninn.bind_bus(bus)

    asyncio.run(
        muninn.on_typed_message(
            "object.audit-entry",
            {
                "kind": "document_ingestion",
                "audited_topic": "object.verdict",
                "stage": "protection_check",
                "decision": "hold",
            },
        )
    )

    assert bus.messages_on("object.context-index") == []


def test_muninn_requests_index_after_saga_sealed_human_approval() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    muninn = Muninn()
    muninn.bind_bus(bus)

    asyncio.run(
        muninn.on_typed_message(
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.approval",
                "stage": "protection_check",
                "decision": "approved",
                "correlation_id": "upload-hil",
                "document_id": "doc-hil",
                "upload_id": "upload-hil",
            },
        )
    )

    assert bus.messages_on("object.context-index")[0].payload["command"] == "index"


def test_muninn_put_get_generic() -> None:
    muninn = Muninn()
    muninn.put_context("resource_state", "vm-1", {"public": False})
    assert muninn.get_context("resource_state", "vm-1") == {"public": False}
    assert muninn.get_context("resource_state", "missing") is None


def test_muninn_ignores_turn_without_id_and_other_topics() -> None:
    muninn = Muninn()
    # A turn payload with no id (neither turn_id nor id) is a no-op: nothing
    # is stored, so the conversation_turns bucket never materializes.
    asyncio.run(muninn.on_typed_message("object.turn", {"question": "hi"}))
    # An unrelated topic is ignored entirely.
    asyncio.run(muninn.on_typed_message("object.verdict", {"turn_id": "t9"}))
    assert muninn.get_context("conversation_turns", "t9") is None
    assert muninn.state_store.data == {}


def test_muninn_introspect_general_and_scoped() -> None:
    muninn = Muninn()
    # Bucket names are single tokens ([a-z0-9-]+) so the introspection
    # tokenizer can match one when the operator names it.
    muninn.put_context("vms", "vm-1", {"public": False})
    muninn.put_context("vms", "vm-2", {"public": True})
    muninn.put_context("costs", "rg-a", {"usd": 12})

    # No bucket named -> a general summary over all buckets/keys.
    general = asyncio.run(muninn.introspect("what state do you hold?", {}))
    assert general.facts["buckets_count"] == 2
    assert general.facts["total_keys"] == 3
    assert "2 state bucket" in general.answer

    # Naming an existing bucket scopes the answer to that bucket.
    scoped = asyncio.run(muninn.introspect("how many vms keys?", {}))
    assert scoped.facts["bucket"] == "vms"
    assert scoped.facts["key_count"] == 2
    assert "vms" in scoped.answer
    assert "2 key(s)" in scoped.answer


# ---------------------------------------------------------------------------
# Mimir - promotion state
# ---------------------------------------------------------------------------


def test_mimir_accepts_and_drains_rule_candidates() -> None:
    mimir = Mimir()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {
                "target_rule_id": "storage.public.deny",
                "proposal_kind": "new",
                "proposed_by": "Norns",
                "source_signal": "handoff_fingerprint",
                "evidence": {"fingerprint": "abc", "occurrence_count": 3},
            },
        )
    )
    assert len(mimir.pending_candidates()) == 1
    mimir.promote("storage.public.deny", source="handoff")
    status = mimir.status("storage.public.deny")
    assert status is not None
    assert status.state == "enforce"
    # promoted candidate is removed from the pending list
    assert all(c.get("target_rule_id") != "storage.public.deny" for c in mimir.pending_candidates())


def test_mimir_quarantines_ungrounded_candidate() -> None:
    """A candidate with no evidence is quarantined, not accepted."""
    mimir = Mimir()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {"target_rule_id": "r1", "proposal_kind": "new", "proposed_by": "Norns"},
        )
    )
    assert mimir.pending_candidates() == ()
    quarantined = mimir.quarantined_candidates()
    assert len(quarantined) == 1
    assert quarantined[0]["quarantine_reason"] == "ungrounded:no_evidence"


def test_mimir_quarantines_missing_provenance() -> None:
    mimir = Mimir()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {"target_rule_id": "r1", "proposal_kind": "new", "evidence": {"x": 1}},
        )
    )
    assert mimir.pending_candidates() == ()
    assert mimir.quarantined_candidates()[0]["quarantine_reason"] == (
        "missing_provenance:proposed_by"
    )


def test_mimir_quarantine_is_bounded_against_poisoning_flood() -> None:
    # Quarantine holds REJECTED candidates - attacker-controlled volume under a
    # poisoning attempt. It must be a bounded ring so a flood cannot exhaust
    # memory (DoS), while keeping the most recent rejects for diagnostics.
    from fdai.agents.mimir import _MAX_QUARANTINE

    mimir = Mimir()
    for i in range(_MAX_QUARANTINE + 50):
        asyncio.run(
            mimir.on_typed_message(
                "object.rule-candidate",
                # No provenance -> guard rejects -> quarantined.
                {"target_rule_id": f"r{i}", "proposal_kind": "new", "evidence": {"x": 1}},
            )
        )
    assert len(mimir.quarantined_candidates()) == _MAX_QUARANTINE


def test_mimir_revoke_flips_state_to_retired() -> None:
    mimir = Mimir()
    mimir.promote("r1", source="manual")
    mimir.revoke("r1")
    assert mimir.status("r1").state == "retired"


# ---------------------------------------------------------------------------
# Norns - fingerprint aggregator
# ---------------------------------------------------------------------------


def test_norns_proposes_candidate_after_threshold() -> None:
    norns = Norns(promotion_threshold=3)
    payload = {"fingerprint": "abc123"}
    for _ in range(3):
        asyncio.run(norns.on_typed_message("object.issue", payload))
    assert norns.occurrences("abc123") == 3
    assert len(norns.pending_candidates) == 1
    assert norns.pending_candidates[0]["evidence"]["fingerprint"] == "abc123"


def test_norns_dedups_candidate_proposals() -> None:
    norns = Norns(promotion_threshold=2)
    payload = {"fingerprint": "same-fp"}
    for _ in range(5):
        asyncio.run(norns.on_typed_message("object.issue", payload))
    # Threshold crossed once, proposal must not repeat.
    assert len(norns.pending_candidates) == 1


# ---------------------------------------------------------------------------
# End-to-end via InMemoryBus
# ---------------------------------------------------------------------------


def test_end_to_end_handoff_flow_via_bus() -> None:
    """A handoff escalation flows through Saga -> Norns -> Mimir."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    norns = Norns(promotion_threshold=3)
    mimir = Mimir()

    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    fp = compute_fingerprint(
        intent_category="q",
        resource_type="r",
        normalized_selector="s",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )

    # Saga escalates three times => Norns crosses threshold, proposes candidate
    for i in range(3):
        asyncio.run(
            saga.escalate_to_github_issue(
                fingerprint=fp,
                emitting_agent="Heimdall",
                intent_category="q",
                failure_reason_code="no_owned_data",
                correlation_id=f"corr-{i}",
            )
        )
        asyncio.run(
            bus.publish(
                "Saga",
                "object.issue",
                {
                    "producer_principal": "Saga",
                    "correlation_id": f"corr-{i}",
                    "fingerprint": fp,
                },
            )
        )

    # Norns should have produced a candidate.
    assert len(norns.pending_candidates) == 1
    # Publish the candidate to Mimir via the bus (Norns as publisher).
    asyncio.run(
        bus.publish(
            "Norns",
            "object.rule-candidate",
            {
                "producer_principal": "Norns",
                "correlation_id": "corr-cand",
                **norns.pending_candidates[0],
                "target_rule_id": "auto-generated",
            },
        )
    )
    assert len(mimir.pending_candidates()) == 1

    # Mimir promotes; Saga can now close the fingerprinted issue.
    mimir.promote("auto-generated", source="handoff")
    saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/1")
    assert saga.github.issues[fp].open is False


def test_norns_publishes_candidate_to_mimir_when_bus_bound() -> None:
    """With a bus bound, Norns is the single writer of object.rule-candidate:
    it auto-publishes each inert candidate its learners form, closing the
    Norns -> Mimir discovery loop without a manual bridge step."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    norns = Norns(promotion_threshold=2)
    mimir = Mimir()
    norns.bind_bus(bus)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    payload = {"fingerprint": "fp-loop"}
    for _ in range(2):
        asyncio.run(norns.on_typed_message("object.issue", payload))

    # Norns formed one candidate and published it; a published candidate is
    # dropped from the buffer, so pending_candidates is empty afterwards.
    assert len(norns.pending_candidates) == 0
    accepted = mimir.pending_candidates()
    assert len(accepted) == 1
    assert accepted[0]["proposed_by"] == "Norns"
    assert accepted[0]["proposal_kind"] == "new"
    assert mimir.quarantined_candidates() == ()


def test_norns_flush_is_idempotent_and_no_op_without_bus() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    # Bus-less: flush publishes nothing and does not raise.
    busless = Norns(promotion_threshold=1)
    asyncio.run(busless.on_typed_message("object.issue", {"fingerprint": "fp-a"}))
    assert len(busless.pending_candidates) == 1  # candidate formed, not published
    assert asyncio.run(busless.flush_candidates()) == 0

    # Bus bound: the candidate is published once; a re-flush republishes
    # nothing (cursor), so Mimir's flood guard never sees a duplicate.
    norns = Norns(promotion_threshold=1)
    norns.bind_bus(bus)
    asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": "fp-b"}))
    assert len(bus.messages_on("object.rule-candidate")) == 1
    assert asyncio.run(norns.flush_candidates()) == 0
    assert len(bus.messages_on("object.rule-candidate")) == 1


def test_norns_throttles_candidate_publication_at_the_rate_limit() -> None:
    """Proposal publication honors the declared rate_limits (agent-pantheon
    7.9): over-budget candidates are throttled (held on the bounded buffer),
    not dropped - they flush on a later pass once the budget refills."""
    from fdai.agents._framework.rate_limiter import RateLimiter

    class _FakeClock:
        def __init__(self) -> None:
            self.t = 0.0

        def now(self) -> float:
            return self.t

    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    norns = Norns(promotion_threshold=1)
    norns.bind_bus(bus)
    clock = _FakeClock()
    # Inject a tiny, clock-controlled budget: 2 proposals/minute.
    norns._proposal_limiter = RateLimiter(per_minute=2, per_hour=100, now=clock.now)

    # Three distinct fingerprints -> three candidates; two publish and are
    # dropped from the buffer, the third is over the per-minute budget and
    # stays queued (throttled, not lost).
    for i in range(3):
        asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": f"fp-{i}"}))
    assert len(norns.pending_candidates) == 1
    assert len(bus.messages_on("object.rule-candidate")) == 2
    assert norns.behavior_snapshot().get("rate_limit_exceeded") == 1

    # Budget refills after the minute window; the held candidate flushes.
    clock.t += 60.0
    assert asyncio.run(norns.flush_candidates()) == 1
    assert len(bus.messages_on("object.rule-candidate")) == 3


def test_norns_pending_buffer_drops_published_candidates() -> None:
    """Published candidates are removed from pending_candidates, so the buffer
    holds only not-yet-published proposals - bounded, with no lifetime-history
    retention (regression guard for the memory-leak fix)."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    norns = Norns(promotion_threshold=1)
    norns.bind_bus(bus)
    # Ten distinct candidates, all within the default 20/min budget -> every
    # one publishes and is dropped from the buffer.
    for i in range(10):
        asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": f"fp-{i}"}))
    assert len(bus.messages_on("object.rule-candidate")) == 10
    assert norns.pending_candidates == []


def test_saga_escalate_publishes_object_issue_and_feeds_fingerprint_loop() -> None:
    """A bus-bound Saga publishes object.issue on escalation (it is the single
    writer of Issue), so recurring handoffs feed Norns' fingerprint learner
    end to end - no manual bridge step - and Mimir accepts the new-rule
    candidate."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    saga.bind_bus(bus)
    norns = Norns(promotion_threshold=2)
    norns.bind_bus(bus)
    mimir = Mimir()
    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    fp = compute_fingerprint(
        intent_category="q",
        resource_type="r",
        normalized_selector="s",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )
    for i in range(2):
        asyncio.run(
            saga.escalate_to_github_issue(
                fingerprint=fp,
                emitting_agent="Heimdall",
                intent_category="q",
                failure_reason_code="no_owned_data",
                correlation_id=f"c-{i}",
            )
        )
    # Saga auto-published object.issue twice -> Norns crossed its threshold and
    # proposed a new-rule candidate -> Mimir's guard accepted it.
    assert len(bus.messages_on("object.issue")) == 2
    assert norns.occurrences(fp) == 2
    accepted = mimir.pending_candidates()
    assert len(accepted) == 1
    assert accepted[0]["proposal_kind"] == "new"


# ---------------------------------------------------------------------------
# Norns - outcome-threshold learner (rubric C2 / #22)
# ---------------------------------------------------------------------------


def _run_outcomes(norns: Norns, target: str, *, rollbacks: int, successes: int) -> None:
    for _ in range(rollbacks):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": target, "result": "rollback"}
            )
        )
    for _ in range(successes):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": target, "result": "success"}
            )
        )


def test_norns_proposes_threshold_adjustment_on_high_rollback() -> None:
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    # 4 rollbacks / 10 total = 0.4 > 0.2 alarm.
    _run_outcomes(norns, "remediate.resize-vm-up", rollbacks=4, successes=6)
    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1
    ev = proposals[0]["evidence"]
    assert ev["target"] == "remediate.resize-vm-up"
    assert ev["sample_size"] == 10
    assert ev["rollback_rate"] == 0.4
    assert proposals[0]["suggested_change"] == "raise_confidence_threshold"


def test_norns_no_threshold_proposal_below_min_samples() -> None:
    norns = Norns(min_outcome_samples=20, rollback_alarm_rate=0.2)
    _run_outcomes(norns, "remediate.x", rollbacks=3, successes=2)  # 5 < 20
    assert norns.pending_candidates == []
    assert norns.outcome_rate("remediate.x") == 0.6


def test_norns_no_threshold_proposal_when_rollback_low() -> None:
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    _run_outcomes(norns, "remediate.safe", rollbacks=1, successes=19)  # 0.05 < 0.2
    assert norns.pending_candidates == []


def test_norns_threshold_proposal_dedups() -> None:
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    _run_outcomes(norns, "remediate.y", rollbacks=5, successes=5)
    _run_outcomes(norns, "remediate.y", rollbacks=5, successes=5)  # keep firing
    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1  # proposed once, then deduped


# ---------------------------------------------------------------------------
# Norns - override learner (rubric C2 / #22)
# ---------------------------------------------------------------------------


def test_norns_proposes_retirement_on_recurring_disable_override() -> None:
    norns = Norns(override_retire_threshold=3)
    for _ in range(3):
        norns.observe_override(
            {"rule_id": "net.public.deny", "mode": "disabled", "event": "create"},
        )
    proposals = [c for c in norns.pending_candidates if c["proposal_kind"] == "retirement"]
    assert len(proposals) == 1
    assert proposals[0]["target_rule_id"] == "net.public.deny"
    assert norns.override_count("net.public.deny") == 3


def test_norns_proposes_revision_on_recurring_downgrade_override() -> None:
    norns = Norns(override_retire_threshold=3)
    for _ in range(3):
        norns.observe_override(
            {"rule_id": "disk.encrypt", "mode": "severity-downgrade", "event": "create"},
        )
    proposals = [c for c in norns.pending_candidates if c["proposal_kind"] == "revision"]
    assert len(proposals) == 1
    assert proposals[0]["target_rule_id"] == "disk.encrypt"


def test_norns_override_below_threshold_no_proposal() -> None:
    norns = Norns(override_retire_threshold=5)
    for _ in range(4):
        norns.observe_override({"rule_id": "r1", "mode": "disabled", "event": "create"})
    assert norns.pending_candidates == []


# ---------------------------------------------------------------------------
# Norns - approval-pattern learner
# ---------------------------------------------------------------------------


def test_norns_proposes_revision_after_recurring_rejections() -> None:
    """Recurring HIL rejections of one action type propose a revision (the safe,
    autonomy-lowering direction) - humans consistently refuse it."""
    norns = Norns(rejection_revise_threshold=3)
    for i in range(3):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "action_type": "remediate.enable-encryption",
                    "state": "rejected",
                    "correlation_id": f"c-{i}",
                },
            )
        )
    proposals = [
        c for c in norns.pending_candidates if c["source_signal"] == "recurring_hil_rejection"
    ]
    assert len(proposals) == 1
    assert proposals[0]["proposal_kind"] == "revision"
    assert proposals[0]["target_rule_id"] == "remediate.enable-encryption"
    assert proposals[0]["evidence"]["rejection_count"] == 3
    assert norns.rejection_count("remediate.enable-encryption") == 3


def test_norns_approvals_alone_propose_nothing() -> None:
    """Approvals are counted for evidence only; the learner never proposes an
    auto-promotion (the risky direction)."""
    norns = Norns(rejection_revise_threshold=2)
    for i in range(5):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "action_type": "ops.restart-service",
                    "state": "approved",
                    "correlation_id": f"a-{i}",
                },
            )
        )
    assert norns.pending_candidates == []
    assert norns.rejection_count("ops.restart-service") == 0


def test_norns_dedups_approval_per_correlation() -> None:
    """A re-delivered decision (at-least-once) is scored once; only a distinct
    correlation advances the rejection count."""
    norns = Norns(rejection_revise_threshold=2)
    for _ in range(2):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "action_type": "remediate.delete-storage",
                    "state": "rejected",
                    "correlation_id": "dup",
                },
            )
        )
    assert norns.rejection_count("remediate.delete-storage") == 1
    assert norns.pending_candidates == []  # threshold 2 not reached (deduped)
    asyncio.run(
        norns.on_typed_message(
            "object.approval",
            {
                "action_type": "remediate.delete-storage",
                "state": "rejected",
                "correlation_id": "distinct",
            },
        )
    )
    assert norns.rejection_count("remediate.delete-storage") == 2
    proposals = [
        c for c in norns.pending_candidates if c["source_signal"] == "recurring_hil_rejection"
    ]
    assert len(proposals) == 1


def test_norns_fingerprint_learner_still_isolated() -> None:
    """Outcome/override learners do not perturb the fingerprint learner."""
    norns = Norns(promotion_threshold=3)
    for _ in range(3):
        asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": "fp-x"}))
    asyncio.run(
        norns.on_typed_message("object.audit-entry", {"action_type": "a", "result": "success"})
    )
    new_rules = [c for c in norns.pending_candidates if c["proposal_kind"] == "new"]
    assert len(new_rules) == 1


def test_norns_outcome_learner_normalizes_action_run_state() -> None:
    """An audit-entry that carries Thor's raw ``state`` (not a normalized
    ``result``) still scores: rolled_back / failed -> adverse, succeeded ->
    success."""
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    for _ in range(4):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": "remediate.z", "state": "rolled_back"}
            )
        )
    for _ in range(6):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": "remediate.z", "state": "succeeded"}
            )
        )
    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1
    assert proposals[0]["evidence"]["rollback_rate"] == 0.4


# ---------------------------------------------------------------------------
# Discovery loop B: Saga republishes outcomes -> Norns learns
# ---------------------------------------------------------------------------


def _saga_on_bus() -> tuple[Saga, InMemoryBus]:
    bus = InMemoryBus(registry=load_pantheon())
    saga = Saga()
    saga.bind_bus(bus)
    return saga, bus


def test_saga_republishes_terminal_action_outcome() -> None:
    saga, bus = _saga_on_bus()
    for state, expected in (
        ("succeeded", "success"),
        ("failed", "failure"),
        ("rolled_back", "rollback"),
    ):
        bus.clear_history()
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"action_type": "remediate.z", "state": state, "correlation_id": "c"},
            )
        )
        entries = bus.messages_on("object.audit-entry")
        assert len(entries) == 1
        assert entries[0].payload["result"] == expected
        assert entries[0].payload["action_type"] == "remediate.z"


def test_saga_prefers_direct_result_over_unmappable_state() -> None:
    """Consistency with Norns (which reads ``result`` before ``state``): a
    producer that stamped a canonical ``result`` but a ``state`` Saga cannot
    map is still republished, using the direct result. Without this the writer
    (Saga) would drop a record the reader (Norns) would have learned."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "action_type": "remediate.z",
                "result": "rollback",
                "state": "some_future_state",
                "correlation_id": "c",
            },
        )
    )
    entries = bus.messages_on("object.audit-entry")
    assert len(entries) == 1
    assert entries[0].payload["result"] == "rollback"


def test_saga_ignores_non_canonical_direct_result() -> None:
    """A junk ``result`` does not bypass the ``state`` mapping: Saga only
    honors a directly-stamped result when it is in the canonical vocabulary,
    so an audit-entry always carries a clean value."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "action_type": "remediate.z",
                "result": "banana",
                "state": "succeeded",
                "correlation_id": "c",
            },
        )
    )
    entries = bus.messages_on("object.audit-entry")
    assert len(entries) == 1
    assert entries[0].payload["result"] == "success"


def test_saga_does_not_republish_intermediate_or_untyped_state() -> None:
    saga, bus = _saga_on_bus()
    # Intermediate state -> no learnable outcome -> no audit-entry.
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {"action_type": "remediate.z", "state": "executing", "correlation_id": "c"},
        )
    )
    # Terminal but no action_type -> nothing to attribute.
    asyncio.run(
        saga.on_typed_message("object.action-run", {"state": "succeeded", "correlation_id": "c"})
    )
    assert bus.messages_on("object.audit-entry") == []


def test_saga_skips_republish_on_empty_correlation() -> None:
    """An empty correlation would give the audit-entry an empty partition key
    (ordering loss) and Norns cannot dedup it - skip the republish."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run", {"action_type": "a", "state": "failed", "correlation_id": ""}
        )
    )
    assert bus.messages_on("object.audit-entry") == []


def test_saga_self_loop_guard_skips_already_republished_record() -> None:
    """Defensive: a record already carrying audited_topic is never
    re-republished, so an audit-of-an-audit loop cannot form even if Saga is
    wired to consume object.audit-entry later."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "action_type": "a",
                "state": "failed",
                "correlation_id": "c",
                "audited_topic": "object.action-run",
            },
        )
    )
    assert bus.messages_on("object.audit-entry") == []


def test_saga_republishes_shadow_flag() -> None:
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {"action_type": "a", "state": "succeeded", "correlation_id": "c", "shadow_mode": True},
        )
    )
    entries = bus.messages_on("object.audit-entry")
    assert len(entries) == 1
    assert entries[0].payload["shadow_mode"] is True


def test_norns_skips_shadow_outcomes() -> None:
    """A shadow 'success' is judged-and-logged, not a real execution - it MUST
    NOT be learned from (it would dilute the real rollback rate)."""
    norns = Norns(min_outcome_samples=1, rollback_alarm_rate=0.0)
    # A shadow rollback that would otherwise trip the alarm -> ignored.
    asyncio.run(
        norns.on_typed_message(
            "object.audit-entry",
            {"action_type": "a", "result": "rollback", "correlation_id": "c", "shadow_mode": True},
        )
    )
    assert norns.pending_candidates == []
    # A real (non-shadow) rollback IS learned.
    asyncio.run(
        norns.on_typed_message(
            "object.audit-entry",
            {"action_type": "a", "result": "rollback", "correlation_id": "d"},
        )
    )
    assert any(c["proposal_kind"] == "threshold_adjustment" for c in norns.pending_candidates)


def test_saga_audit_entry_drives_norns_outcome_learning() -> None:
    """End to end: Saga republishes terminal outcomes, Norns (subscribed to
    object.audit-entry) scores the rollback rate and proposes a threshold
    adjustment - the closed discovery loop."""
    saga, bus = _saga_on_bus()
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    bus.subscribe("object.audit-entry", "Norns", norns.on_typed_message)

    # 4 failed actions - each emits FAILED then ROLLED_BACK (2 audit-entries,
    # same correlation) -> deduped to 1 adverse each. 6 succeeded.
    for i in range(4):
        for state in ("failed", "rolled_back"):
            asyncio.run(
                saga.on_typed_message(
                    "object.action-run",
                    {"action_type": "remediate.z", "state": state, "correlation_id": f"f{i}"},
                )
            )
    for i in range(6):
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"action_type": "remediate.z", "state": "succeeded", "correlation_id": f"s{i}"},
            )
        )

    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1
    assert proposals[0]["evidence"]["sample_size"] == 10  # dedup: 4 adverse + 6 success
    assert proposals[0]["evidence"]["rollback_rate"] == 0.4


def test_norns_dedups_outcome_per_correlation() -> None:
    """A single action that emits FAILED then ROLLED_BACK is scored once."""
    norns = Norns()
    # One failed action: FAILED + ROLLED_BACK, same correlation -> 1 adverse.
    for result in ("failure", "rollback"):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry",
                {"action_type": "a", "result": result, "correlation_id": "same"},
            )
        )
    # One success, distinct correlation.
    asyncio.run(
        norns.on_typed_message(
            "object.audit-entry",
            {"action_type": "a", "result": "success", "correlation_id": "other"},
        )
    )
    # Deduped: 1 adverse + 1 success = 0.5 rollback rate (NOT 2 adverse / 3 = 0.67).
    assert norns.outcome_rate("a") == 0.5


def test_norns_constructor_rejects_misconfiguration() -> None:
    """Out-of-range config would make the learner propose on thin evidence."""
    with pytest.raises(ValueError, match="promotion_threshold"):
        Norns(promotion_threshold=0)
    with pytest.raises(ValueError, match="rollback_alarm_rate"):
        Norns(rollback_alarm_rate=1.5)
    with pytest.raises(ValueError, match="min_outcome_samples"):
        Norns(min_outcome_samples=0)
    with pytest.raises(ValueError, match="override_retire_threshold"):
        Norns(override_retire_threshold=0)
