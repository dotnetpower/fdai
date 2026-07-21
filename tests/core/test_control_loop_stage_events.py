"""Integration test: the ControlLoop emits :class:`StageEvent` records
for every observable stage transition.

Uses :class:`RecordingStagePublisher` to capture the emit stream and
asserts the shape + order of stages seen on the *abstain* path (which is
the only path exercised by a rule-less T0 setup) and the *dedupe* path.

The rule-matched / execute / gate paths would require a full test
harness (rule catalog, ActionBuilder, ExecutorMI, RiskGate) and are
covered by higher-level scenario replays; those already run through
:class:`ControlLoop.process`, and the emit points are the same code
paths regardless of the outcome, so the shape assertions here plus
the existing suite are sufficient regression coverage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.control_loop import ControlLoop, ControlLoopOutcome
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import RuleIndex, T0Engine
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.core.tiers.t1_lightweight.tier import T1Tier
from fdai.core.trust_router import TrustRouter
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.testing import RecordingStagePublisher
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _validator() -> JsonSchemaEventValidator:
    return JsonSchemaEventValidator(JsonSchemaContractValidator(PackageResourceSchemaRegistry()))


def _event_dict(idempotency: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000123",
        "idempotency_key": idempotency,
        "source": "test_source",
        "event_type": "novel.event",
        "detected_at": datetime.now(tz=UTC).isoformat(),
        "ingested_at": datetime.now(tz=UTC).isoformat(),
        "mode": Mode.SHADOW.value,
        "payload": {
            "resource": {"type": "compute.vm.novel", "id": "res-01"},
        },
    }


class _NoopPublisher:
    async def publish(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN201, ARG002
        raise AssertionError("publisher MUST NOT be invoked on an abstain path")


def _make_executor(audit: InMemoryStateStore, tmp_path: Path) -> ShadowExecutor:
    return ShadowExecutor(
        publisher=_NoopPublisher(),
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=tmp_path),
        resource_lock=ResourceLockManager(),
    )


def _make_loop(
    *,
    stage_publisher,
    t1_engine: T1Tier | None = None,
    audit: InMemoryStateStore | None = None,
    tmp_path: Path,
) -> ControlLoop:
    store = audit if audit is not None else InMemoryStateStore()
    index = RuleIndex.build(rules=[])
    return ControlLoop(
        event_ingest=EventIngest(validator=_validator()),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index),
        action_builder=ActionBuilder(action_types_by_name={}),
        executor=_make_executor(store, tmp_path),
        audit_store=store,
        rules_by_id={},
        t1_engine=t1_engine,
        stage_publisher=stage_publisher,
    )


# ---------------------------------------------------------------------------
# Default publisher is NullStagePublisher: absent argument keeps the emit
# stream silent - preserving the backward-compatible no-observation posture.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_publisher_emits_nothing(tmp_path: Path) -> None:
    recorder = RecordingStagePublisher()  # not passed to the loop
    loop = _make_loop(stage_publisher=None, tmp_path=tmp_path)
    result = await loop.process(_event_dict("evt-a"))
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert len(recorder.events) == 0


# ---------------------------------------------------------------------------
# T1-unavailable fallback path: ingest.done -> route.done -> audit.done.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t1_unavailable_emits_ingest_route_audit(tmp_path: Path) -> None:
    recorder = RecordingStagePublisher()
    loop = _make_loop(stage_publisher=recorder, tmp_path=tmp_path)
    result = await loop.process(_event_dict("evt-abstain-routing"))
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING

    stages_in_order = [(e.stage, e.phase) for e in recorder.events]
    assert stages_in_order == [
        (StageName.INGEST, StagePhase.DONE),
        (StageName.ROUTE, StagePhase.DONE),
        (StageName.AUDIT, StagePhase.DONE),
    ]
    route_evt = recorder.by_stage(StageName.ROUTE)[0]
    assert route_evt.detail["routed_to"] == "t1"
    ingest_evt = recorder.by_stage(StageName.INGEST)[0]
    assert ingest_evt.detail["mode"] == Mode.SHADOW.value
    assert ingest_evt.detail["incident_id"] is None
    audit_evt = recorder.by_stage(StageName.AUDIT)[0]
    assert audit_evt.detail["outcome"] == "abstained_routing"


# ---------------------------------------------------------------------------
# Dedupe path: no Event object, so no emits (documented behaviour).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedupe_path_emits_nothing(tmp_path: Path) -> None:
    recorder = RecordingStagePublisher()
    loop = _make_loop(stage_publisher=recorder, tmp_path=tmp_path)
    payload = _event_dict("evt-dedupe")
    first = await loop.process(payload)
    assert first.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    # Reset the recorder so we assert only on the second (duplicate) call.
    recorder.clear()
    second = await loop.process(payload)
    assert second.outcome is ControlLoopOutcome.DEDUPED
    assert len(recorder.events) == 0


# ---------------------------------------------------------------------------
# Join keys: every event carries the same event_id / correlation_id
# so a downstream FE can group emits per idempotency key.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_events_share_event_id(tmp_path: Path) -> None:
    recorder = RecordingStagePublisher()
    loop = _make_loop(stage_publisher=recorder, tmp_path=tmp_path)
    await loop.process(_event_dict("evt-share"))
    ids = {e.event_id for e in recorder.events}
    corr_ids = {e.correlation_id for e in recorder.events}
    assert len(ids) == 1
    assert len(corr_ids) == 1


@pytest.mark.asyncio
async def test_audit_rows_preserve_explicit_correlation_id(tmp_path: Path) -> None:
    recorder = RecordingStagePublisher()
    audit = InMemoryStateStore()
    loop = _make_loop(stage_publisher=recorder, audit=audit, tmp_path=tmp_path)
    payload = _event_dict("evt-audit-correlation")
    payload["correlation_id"] = "corr-audit-correlation"

    await loop.process(payload)

    entries = [row["entry"] for row in audit.audit_entries]
    assert entries
    assert {entry.get("correlation_id") for entry in entries} == {"corr-audit-correlation"}


# ---------------------------------------------------------------------------
# T1 fallback path: verify.done fires again for T1, then audit.done.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t1_fallback_emits_second_verify(tmp_path: Path) -> None:
    recorder = RecordingStagePublisher()
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(dim=32),
        pattern_library=InMemoryPatternLibrary(),
    )
    loop = _make_loop(stage_publisher=recorder, t1_engine=tier, tmp_path=tmp_path)
    # A known resource type with no deterministic rule routes directly to
    # T1. The empty pattern library then abstains without invoking T0.
    result = await loop.process(_event_dict("evt-t1"))
    assert result.outcome is ControlLoopOutcome.T1_ABSTAINED
    verify_events = recorder.by_stage(StageName.VERIFY)
    assert len(verify_events) == 1
    assert verify_events[0].detail["tier"] == "t1"
