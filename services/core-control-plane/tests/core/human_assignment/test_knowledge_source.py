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
