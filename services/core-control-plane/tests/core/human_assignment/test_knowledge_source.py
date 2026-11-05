"""Exact metadata, current admission, and monotonic withdrawal are independent of publication."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.human_assignment.knowledge_source import HandoverKnowledgeSourceCheck
from fdai.core.human_assignment.knowledge_stage import HandoverKnowledgeStage
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.handover_checklist import HANDOVER_SLOTS, checklist_defaults
from fdai_service_contracts.handover_knowledge import notice_for_source

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def goal_record():
    return {
        "goal_id": "goal:example",
        "subject_ref": "human:subject",
        "agent_name": "Muninn",
        "assignment_case_id": "case:example",
        "scope_ref": "scope:platform",
        "source_revision": "ownership:1",
        "prompt_ref": "template:1",
        "priority": 90,
        "state": "ready_for_review",
        "revision": 7,
        "evidence": [
            {
                "slot": slot,
                "evidence_ref": "doc:example:v1",
                "digest": "a" * 64,
                "kind": "document",
            }
            for slot in HANDOVER_SLOTS
        ],
        **checklist_defaults(),
    }


class Reader:
    def __init__(self):
        self.record = goal_record()
        self.available = True
        self.error = False
        self.calls = 0
        self.current = True

    async def read(self, notice):
        if self.error:
            raise OSError("synthetic source outage")
        return deepcopy(self.record)

    async def document_admitted(self, notice, *, evidence_ref, digest):
        self.calls += 1
        return self.available

    async def contribution_current(self, notice):
        return self.current


async def test_complete_source_rechecks_after_document_admission_without_copying_subject():
    reader = Reader()
    notice = notice_for_source(reader.record, source="operator", at=NOW)
    result = await HandoverKnowledgeSourceCheck(reader, lambda: NOW).check(notice)
    assert result.disposition == "admitted"
    assert reader.calls == 1
    assert "human:subject" not in result.model_dump_json()
    assert result.may_promote is result.execution_authority is False


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"state": "stale"}, "withdrawn"),
        ({"state": "in_progress"}, "gap"),
        ({"checklist_version": None}, "gap"),
        ({"evidence": [None]}, "held"),
    ],
)
async def test_unavailable_evidence_does_not_become_positive_candidate(change, expected):
    reader = Reader()
    reader.record.update(change)
    notice = notice_for_source(reader.record, source="operator", at=NOW)
    decision = await HandoverKnowledgeSourceCheck(reader, lambda: NOW).check(notice)
    assert decision.disposition == expected
    assert not decision.evidence_refs


async def test_changed_source_and_provider_outage_are_not_document_deletion():
    reader = Reader()
    notice = notice_for_source(reader.record, source="operator", at=NOW)
    stage = HandoverKnowledgeStage(
        "Forseti",
        InMemoryStateStore(),
        HandoverKnowledgeSourceCheck(reader, lambda: NOW),
        lambda: NOW,
    )
    reader.record["revision"] = 8
    assert (await stage.check(notice)).reason == "source_changed"
    reader.error = True
    assert (await stage.check(notice)).disposition == "held"
    reader.error = False
    reader.record = None
    assert (await stage.check(notice)).disposition == "withdrawn"


async def test_same_document_with_conflicting_digests_requires_arbitration():
    reader = Reader()
    reader.record["evidence"][1]["digest"] = "b" * 64
    notice = notice_for_source(reader.record, source="core", at=NOW)
    assert (
        await HandoverKnowledgeSourceCheck(reader, lambda: NOW).check(notice)
    ).disposition == "conflict"


async def test_withdrawal_survives_restart_and_cannot_be_reversed_at_same_revision():
    reader, store = Reader(), InMemoryStateStore()
    clock = [NOW]
    source = HandoverKnowledgeSourceCheck(reader, lambda: clock[0])
    stage = HandoverKnowledgeStage("Muninn", store, source, lambda: clock[0])
    notice = notice_for_source(reader.record, source="operator", at=NOW)
    admitted = await stage.record(await stage.check(notice))
    reader.available = False
    assert (await stage.record(await stage.check(notice))).disposition == "withdrawn"
    reader.available = True
    clock[0] += timedelta(minutes=5)
    later = notice_for_source(reader.record, source="operator", at=clock[0])
    restarted = HandoverKnowledgeStage("Muninn", store, source, lambda: clock[0])
    assert (await restarted.record(await restarted.check(later))).disposition == "withdrawn"
    assert (await restarted.record(admitted)).disposition == "withdrawn"


def test_same_goal_name_in_independent_source_namespaces_has_distinct_identity():
    core = notice_for_source(goal_record(), source="core", at=NOW)
    operator = notice_for_source(goal_record(), source="operator", at=NOW)
    assert core.source_id != operator.source_id
    assert core.notice_id != operator.notice_id


async def test_revoked_contribution_withdraws_an_otherwise_admitted_document():
    reader = Reader()
    reader.current = False
    notice = notice_for_source(reader.record, source="operator", at=NOW)
    result = await HandoverKnowledgeSourceCheck(reader, lambda: NOW).check(notice)
    assert result.disposition == "withdrawn"
    assert reader.calls == 0


async def test_document_io_cannot_slide_notice_deadline_or_hide_goal_revision_change():
    reader = Reader()
    clock = [NOW]
    notice = notice_for_source(reader.record, source="operator", at=NOW)
    stage = HandoverKnowledgeStage(
        "Forseti",
        InMemoryStateStore(),
        HandoverKnowledgeSourceCheck(reader, lambda: clock[0]),
        lambda: clock[0],
    )

    async def expire(*args, **kwargs):
        clock[0] += timedelta(minutes=5)
        return True

    reader.document_admitted = expire
    assert (await stage.check(notice)).disposition == "held"
    clock[0] = NOW

    async def revise(*args, **kwargs):
        reader.record["revision"] = 8
        return True

    reader.document_admitted = revise
    assert (await stage.check(notice)).reason == "source_changed"


async def test_failed_owner_audit_never_creates_a_stage_receipt(monkeypatch):
    reader, store = Reader(), InMemoryStateStore()
    stage = HandoverKnowledgeStage(
        "Muninn",
        store,
        HandoverKnowledgeSourceCheck(reader, lambda: NOW),
        lambda: NOW,
    )
    notice = notice_for_source(reader.record, source="operator", at=NOW)

    async def unavailable(*args, **kwargs):
        raise OSError("synthetic atomic audit failure")

    monkeypatch.setattr(store, "write_state_with_audit_if_absent", unavailable)
    with pytest.raises(OSError):
        await stage.record(await stage.check(notice))
    assert not await store.read_states("human_assignment:knowledge:", limit=10)


async def test_normal_control_loop_defers_source_notices_to_actual_pantheon_owners():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from fdai.core.control_loop._process import _process_normalized_event
    from fdai.shared.contracts.models import Event, Mode
    from fdai_service_contracts.handover_knowledge import KNOWLEDGE_SOURCE_EVENT

    store = InMemoryStateStore()
    ordinary = AsyncMock(
        side_effect=AssertionError("non-action notice entered ordinary action flow")
    )
    host = SimpleNamespace(
        _audit_store=store,
        _emit_stage=AsyncMock(),
        _correlate_incident_id=lambda event: None,
        _maybe_fire_workflows=ordinary,
    )
    event = Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key="knowledge:test",
        source="scheduler",
        event_type=KNOWLEDGE_SOURCE_EVENT,
        resource_ref="handover:example",
        payload={},
        detected_at=NOW,
        ingested_at=NOW,
        mode=Mode.SHADOW,
    )
    result = await _process_normalized_event(host, event)
    assert result.reason == "pantheon_shadow_review_owner"
    ordinary.assert_not_called()
    assert store.audit_entries[-1]["entry"]["action_kind"] == "handover.knowledge_source_routed"
    assert await store.verify_chain()


async def test_knowledge_source_and_stage_edge_branches(monkeypatch):
    from unittest.mock import AsyncMock

    from fdai_service_contracts.handover_knowledge import HandoverKnowledgeDecision

    # HandoverKnowledgeStage owner and check validations
    store = InMemoryStateStore()
    reader = Reader()
    source = HandoverKnowledgeSourceCheck(reader, lambda: NOW)
    with pytest.raises(ValueError, match="owner is unsupported"):
        HandoverKnowledgeStage("Thor", store, source, lambda: NOW)

    stage = HandoverKnowledgeStage("Muninn", store, source, lambda: NOW)
    with pytest.raises(TypeError, match="HandoverKnowledgeNotice"):
        await stage.check("not-a-notice")  # type: ignore[arg-type]

    notice = notice_for_source(reader.record, source="operator", at=NOW)
    naive_stage = HandoverKnowledgeStage("Muninn", store, source, lambda: datetime(2026, 9, 14, 12))
    assert (await naive_stage.check(notice)).reason == "check_expired"

    # source.check returning mismatched notice -> held / source_unavailable
    from types import SimpleNamespace

    other_rec = {**goal_record(), "goal_id": "goal:other"}
    other_notice = notice_for_source(other_rec, source="operator", at=NOW)
    bad_source_stage = HandoverKnowledgeStage(
        "Muninn",
        store,
        SimpleNamespace(
            check=AsyncMock(
                return_value=HandoverKnowledgeDecision(
                    notice=other_notice, disposition="held", reason="source_changed"
                )
            )
        ),
        lambda: NOW,
    )
    assert (await bad_source_stage.check(notice)).reason == "source_unavailable"

    # already_recorded and record branches
    decision = await stage.check(notice)
    assert await stage.already_recorded(decision) is False
    recorded = await stage.record(decision)
    assert await stage.already_recorded(recorded) is True
    # Recording exact same decision again returns immediately (line 119)
    assert await stage.record(decision) == recorded

    # old_order > new_order -> source_changed (line 107)
    older_rec = {**reader.record, "revision": 6}
    older_notice = notice_for_source(older_rec, source="operator", at=NOW - timedelta(minutes=1))
    older_decision = HandoverKnowledgeDecision(
        notice=older_notice,
        disposition="admitted",
        reason="source_admitted",
        evidence_refs=decision.evidence_refs,
        evidence_digests=decision.evidence_digests,
    )
    assert (await stage.record(older_decision)).reason == "source_changed"

    # old_order == new_order with different source_digest -> evidence_conflict (line 113)
    diff_digest_notice = notice.model_copy(update={"source_digest": "f" * 64})
    diff_decision = HandoverKnowledgeDecision(
        notice=diff_digest_notice,
        disposition="admitted",
        reason="source_admitted",
        evidence_refs=decision.evidence_refs,
        evidence_digests=decision.evidence_digests,
    )
    conflict_res = await stage.record(diff_decision)
    assert conflict_res.disposition == "conflict"

    # Malformed stored revision (line 92)
    key = f"human_assignment:knowledge:Muninn:{notice.source_id}"
    await store.write_state(key, {"revision": 0, "decision": decision.model_dump(mode="json")})
    with pytest.raises(ValueError, match="revision is malformed"):
        await stage.record(decision)

    # Concurrent CAS failure across all 4 attempts (lines 137->86, 139)
    await store.write_state(
        key, {"revision": 1, "decision": older_decision.model_dump(mode="json")}
    )
    orig_cas = store.compare_and_set_state_with_audit
    monkeypatch.setattr(store, "compare_and_set_state_with_audit", AsyncMock(return_value=False))
    with pytest.raises(RuntimeError, match="changed concurrently"):
        await stage.record(decision)
    monkeypatch.setattr(store, "compare_and_set_state_with_audit", orig_cas)

    # HandoverKnowledgeSourceCheck edge branches
    r2 = Reader()
    n2 = notice_for_source(r2.record, source="operator", at=NOW)
    sc2 = HandoverKnowledgeSourceCheck(r2, lambda: NOW)

    # goal_id mismatch or non-int revision (line 44)
    r2.record["goal_id"] = "goal:changed"
    assert (await sc2.check(n2)).reason == "source_changed"

    # evidence not list (line 54)
    r2 = Reader()
    r2.record["evidence"] = "not-a-list"
    n2 = notice_for_source(r2.record, source="operator", at=NOW)
    assert (
        await HandoverKnowledgeSourceCheck(r2, lambda: NOW).check(n2)
    ).reason == "source_unavailable"

    # evidence item with non-str evidence_ref (branch 60->56)
    r2 = Reader()
    r2.record["evidence"].append({"evidence_ref": 123, "digest": "a" * 64})
    n2 = notice_for_source(r2.record, source="operator", at=NOW)
    assert (await HandoverKnowledgeSourceCheck(r2, lambda: NOW).check(n2)).disposition == "admitted"

    # project_checklist raising ValueError (lines 67-68)
    import fdai.core.human_assignment.knowledge_source as ks_mod

    r2 = Reader()
    n2 = notice_for_source(r2.record, source="operator", at=NOW)
    orig_proj = ks_mod.project_checklist
    monkeypatch.setattr(
        ks_mod,
        "project_checklist",
        lambda _rec: (_ for _ in ()).throw(ValueError("bad checklist")),
    )
    assert (
        await HandoverKnowledgeSourceCheck(r2, lambda: NOW).check(n2)
    ).reason == "source_unavailable"
    monkeypatch.setattr(ks_mod, "project_checklist", orig_proj)

    # Post-document-I/O second read changes: None (80), stale (82), unserializable (85-86)
    for final_val, expected_disp in [
        (None, "withdrawn"),
        ({**goal_record(), "state": "stale"}, "withdrawn"),
        ({"bad": object()}, "held"),
    ]:
        r3 = Reader()
        n3 = notice_for_source(r3.record, source="operator", at=NOW)

        async def mutate_on_doc(_ntc, *, evidence_ref, digest, target=r3, val=final_val):
            target.record = val
            return True

        r3.document_admitted = mutate_on_doc
        res3 = await HandoverKnowledgeSourceCheck(r3, lambda: NOW).check(n3)
        assert res3.disposition == expected_disp

    r4 = Reader()
    n4 = notice_for_source(r4.record, source="operator", at=NOW)
    contrib_calls = 0

    async def contrib_flips(_ntc):
        nonlocal contrib_calls
        contrib_calls += 1
        return contrib_calls == 1

    r4.contribution_current = contrib_flips
    assert (
        await HandoverKnowledgeSourceCheck(r4, lambda: NOW).check(n4)
    ).disposition == "withdrawn"
