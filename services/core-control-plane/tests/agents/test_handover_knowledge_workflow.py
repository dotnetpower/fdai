"""Actual fixed-owner subscribers consume source checks; labels alone confer no authority."""

from __future__ import annotations

import asyncio

import pytest
from fdai.agents import AssignmentWorkflowBindings, PantheonRuntime
from fdai.core.human_assignment.knowledge_source import HandoverKnowledgeSourceCheck
from fdai.core.human_assignment.knowledge_stage import HandoverKnowledgeStage
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.handover_knowledge import KNOWLEDGE_SOURCE_EVENT, notice_for_source

from tests.agents.test_assignment_workflow import _stop
from tests.agents.test_runtime_chain import LiveInMemoryEventBus
from tests.core.human_assignment.test_knowledge_source import NOW, Reader
from tests.core.human_assignment.test_request_processor import _processor


class ResultBus(LiveInMemoryEventBus):
    def __init__(self):
        super().__init__()
        self.terminal = asyncio.Event()
        self.results = []

    async def publish(self, topic, key, payload):
        receipt = await super().publish(topic, key=key, payload=payload)
        if (
            topic == "object.audit-entry"
            and payload.get("audited_topic") == "object.rule"
            and payload.get("kind") == "handover_knowledge"
        ):
            self.results.append(payload)
            self.terminal.set()
        return receipt


def _runtime(reader, bus, stores=None, *, compiler=None, reviewer=None):
    processor = _processor()
    stores = stores or {
        name: InMemoryStateStore() for name in ("Forseti", "Muninn", "Norns", "Mimir")
    }
    return (
        PantheonRuntime.build(
            provider=bus,
            raw_event_topic="knowledge.raw",
            assignment_workflow=AssignmentWorkflowBindings(
                processor.validate,
                processor.validate_review,
                processor,
                knowledge_stages=tuple(
                    HandoverKnowledgeStage(
                        name,
                        store,
                        HandoverKnowledgeSourceCheck(reader, lambda: NOW),
                        lambda: NOW,
                    )
                    for name, store in stores.items()
                ),
                semantic_compiler=compiler,
                semantic_reviewer=reviewer,
            ),
        ),
        stores,
    )


async def _ingest(runtime, bus, record):
    notice = notice_for_source(record, source="operator", at=NOW)
    bus.terminal.clear()
    await runtime.ingest_raw_event(
        {
            "event_type": KNOWLEDGE_SOURCE_EVENT,
            "source": "synthetic-scheduler",
            "event_id": notice.notice_id,
            "idempotency_key": notice.notice_id,
            "correlation_id": notice.source_id,
            "resource_ref": "handover:test",
            "payload": {"notice": notice.model_dump(mode="json"), "private_text": "MUST NOT LEAK"},
        }
    )
    await asyncio.wait_for(bus.terminal.wait(), timeout=3)
    return bus.results[-1]["knowledge"]


async def test_real_owner_chain_records_review_required_candidate_without_catalog_or_iam_change():
    reader, bus = Reader(), ResultBus()
    runtime, stores = _runtime(reader, bus)
    task = asyncio.create_task(runtime.run())
    try:
        result = await _ingest(runtime, bus, reader.record)
        assert result["disposition"] == "admitted"
        assert result["review_required"] is True
        assert result["may_promote"] is result["execution_authority"] is False
        for owner, store in stores.items():
            assert await store.read_states(f"human_assignment:knowledge:{owner}:", limit=5)
            assert not await store.read_states("operator-handover-goal:", limit=5)
        assert not bus._records.get("object.action-run")
        assert not runtime.agents["Mimir"]._pending_candidates
        for messages in bus._records.values():
            assert all(
                "MUST NOT LEAK" not in str(row[1]) and "human:subject" not in str(row[1])
                for row in messages
            )
        assert all(
            row[1]["producer_principal"] == "Norns" for row in bus._records["object.rule-candidate"]
        )
    finally:
        await _stop(runtime, task)


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("deleted", "withdrawn"),
        ("acl", "withdrawn"),
        ("outage", "held"),
        ("conflict", "conflict"),
        ("gate", "held"),
    ],
)
async def test_negative_source_dispositions_survive_all_actual_owners(failure, expected):
    reader, bus = Reader(), ResultBus()
    original = reader.record
    if failure == "deleted":
        reader.record = None
    if failure == "acl":
        reader.available = False
    if failure == "outage":
        reader.error = True
    if failure == "conflict":
        reader.record["evidence"][1]["digest"] = "b" * 64
    runtime, _ = _runtime(reader, bus)
    if failure == "gate":
        runtime.agents["Norns"].bind_candidate_publication_gate(lambda: False)
    task = asyncio.create_task(runtime.run())
    try:
        result = await _ingest(runtime, bus, original)
        assert result["disposition"] == expected
        assert not result["evidence_refs"]
        assert not bus._records.get("object.action-run")
        if failure == "conflict":
            assert bus._records["object.arbitration-decision"][0][1]["producer_principal"] == "Odin"
            assert result["reason"] == "clarification_required"
    finally:
        await _stop(runtime, task)


async def test_mimir_exact_redelivery_does_not_turn_an_admitted_source_into_a_flood():
    reader, bus = Reader(), ResultBus()
    runtime, _ = _runtime(reader, bus)
    task = asyncio.create_task(runtime.run())
    try:
        await _ingest(runtime, bus, reader.record)
        candidate = dict(bus._records["object.rule-candidate"][0][1])
        for _ in range(4):
            bus.terminal.clear()
            await runtime.bridge.publish("Norns", "object.rule-candidate", candidate)
            await asyncio.wait_for(bus.terminal.wait(), timeout=3)
            assert bus.results[-1]["knowledge"]["disposition"] == "admitted"
        reader.available = False
        bus.terminal.clear()
        await runtime.bridge.publish("Norns", "object.rule-candidate", candidate)
        await asyncio.wait_for(bus.terminal.wait(), timeout=3)
        assert bus.results[-1]["knowledge"]["disposition"] == "withdrawn"
    finally:
        await _stop(runtime, task)


async def test_failed_saga_seal_does_not_reach_memory_or_learning(monkeypatch):
    reader, bus = Reader(), ResultBus()
    runtime, stores = _runtime(reader, bus)
    attempted = asyncio.Event()

    def fail_audit(*args, **kwargs):
        attempted.set()
        raise OSError("synthetic Saga audit failure")

    monkeypatch.setattr(runtime.agents["Saga"].audit_chain, "append", fail_audit)
    notice = notice_for_source(reader.record, source="operator", at=NOW)
    task = asyncio.create_task(runtime.run())
    try:
        await runtime.ingest_raw_event(
            {
                "event_type": KNOWLEDGE_SOURCE_EVENT,
                "idempotency_key": notice.notice_id,
                "correlation_id": notice.source_id,
                "payload": {"notice": notice.model_dump(mode="json")},
            }
        )
        await asyncio.wait_for(attempted.wait(), timeout=3)
        assert not await stores["Muninn"].read_states("human_assignment:knowledge:", limit=10)
        assert not bus._records.get("object.rule-candidate")
        assert not bus.results
    finally:
        await _stop(runtime, task)


async def test_real_norns_and_mimir_compile_and_verify_private_semantic_packages():
    from dataclasses import replace

    from tests.rule_catalog.pipeline.distill.test_handover_semantics import fixture

    compiler, reviewer, _ = fixture()
    compiler = replace(compiler, clock=lambda: NOW)
    reviewer = replace(reviewer, clock=lambda: NOW)
    reader, bus = Reader(), ResultBus()
    runtime, _ = _runtime(reader, bus, compiler=compiler, reviewer=reviewer)
    task = asyncio.create_task(runtime.run())
    try:
        assert (await _ingest(runtime, bus, reader.record))["disposition"] == "admitted"
        semantic = bus.results[-1]["semantic"]
        assert semantic["rule_count"] == semantic["ontology_count"] == 1
        assert semantic["disposition"] == "review_required"
        assert semantic["promotion_authority"] is semantic["execution_authority"] is False
        assert compiler.distiller.calls == 1
        assert not runtime.agents["Mimir"]._pending_candidates
        assert not bus._records.get("object.action-run")
        assert all(
            "Example service" not in str(row[1]) for rows in bus._records.values() for row in rows
        )
        candidate = dict(bus._records["object.rule-candidate"][0][1])
        bus.terminal.clear()
        await runtime.bridge.publish("Norns", "object.rule-candidate", candidate)
        await asyncio.wait_for(bus.terminal.wait(), timeout=3)
        assert bus.results[-1]["semantic"] == semantic
        assert compiler.distiller.calls == 1
        reader.available = False
        bus.terminal.clear()
        await runtime.bridge.publish("Norns", "object.rule-candidate", candidate)
        await asyncio.wait_for(bus.terminal.wait(), timeout=3)
        assert bus.results[-1]["knowledge"]["disposition"] == "withdrawn"
        assert "semantic" not in bus.results[-1]
    finally:
        await _stop(runtime, task)


async def test_closed_norns_gate_never_invokes_semantic_compiler():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    compiler = SimpleNamespace(compile=AsyncMock())
    reviewer = SimpleNamespace(review=AsyncMock())
    reader, bus = Reader(), ResultBus()
    runtime, _ = _runtime(reader, bus, compiler=compiler, reviewer=reviewer)
    runtime.agents["Norns"].bind_candidate_publication_gate(lambda: False)
    task = asyncio.create_task(runtime.run())
    try:
        assert (await _ingest(runtime, bus, reader.record))["disposition"] == "held"
        compiler.compile.assert_not_awaited()
        reviewer.review.assert_not_awaited()
    finally:
        await _stop(runtime, task)


@pytest.mark.parametrize("withdrawn", [False, True])
async def test_negative_candidate_rechecks_retention_even_when_publication_is_closed(withdrawn):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    compiler = SimpleNamespace(compile=AsyncMock())
    reviewer = SimpleNamespace(maintain=AsyncMock(return_value=0), review=AsyncMock())
    reader, bus = Reader(), ResultBus()
    if withdrawn:
        reader.available = False
    runtime, _ = _runtime(reader, bus, compiler=compiler, reviewer=reviewer)
    runtime.agents["Norns"].bind_candidate_publication_gate(lambda: False)
    task = asyncio.create_task(runtime.run())
    try:
        result = await _ingest(runtime, bus, reader.record)
        assert result["disposition"] == ("withdrawn" if withdrawn else "held")
        reviewer.maintain.assert_awaited_once()
        assert reviewer.maintain.await_args.kwargs["withdrawn"] is withdrawn
        compiler.compile.assert_not_awaited()
        reviewer.review.assert_not_awaited()
        assert not bus._records.get("object.action-run")
    finally:
        await _stop(runtime, task)


async def test_failed_retention_check_never_emits_semantic_success():
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from tests.rule_catalog.pipeline.distill.test_handover_semantics import fixture

    compiler, _, _ = fixture()
    compiler = replace(compiler, clock=lambda: NOW)
    reviewer = SimpleNamespace(
        maintain=AsyncMock(side_effect=OSError("Synthetic source policy unavailable")),
        review=AsyncMock(),
    )
    reader, bus = Reader(), ResultBus()
    runtime, _ = _runtime(reader, bus, compiler=compiler, reviewer=reviewer)
    task = asyncio.create_task(runtime.run())
    try:
        result = await _ingest(runtime, bus, reader.record)
        assert result["disposition"] == "held"
        assert "semantic" not in bus.results[-1]
        reviewer.review.assert_not_awaited()
    finally:
        await _stop(runtime, task)
