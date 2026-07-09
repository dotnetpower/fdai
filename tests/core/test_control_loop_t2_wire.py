"""ControlLoop T2 wire test.

Covers the scope-expansion.md § 3.7 wiring: when ``t2_engine`` is supplied, an
event that T0 (and T1, if wired) abstained on falls through to T2 for a
shadow-only reasoning log. T2's verdict does NOT execute in this wiring -
building an :class:`Action` from the eligible candidate and routing it through
the risk-gate is a separate P2/P3 step, mirroring the shadow-only T1 reuse log.

Minimal by design: the T2 tier itself is unit-tested in
``tests/core/tiers/t2_reasoning/``. What matters here is the WIRE:

- ``t2_engine=None`` -> loop behaves exactly as before (regression-free).
- ``_consult_t2`` maps the gate verdict to a T2 outcome and writes the
  documented ``control_loop.t2_evaluate`` audit row without executing.
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
from fdai.core.quality_gate.gate import (
    QualityCandidate,
    QualityDecision,
    QualityOutcome,
)
from fdai.core.tiers.t0_deterministic import RuleIndex, T0Engine
from fdai.core.tiers.t2_reasoning import T2Outcome, T2Tier
from fdai.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
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
        "payload": {"resource": {"type": "compute.vm.novel", "id": "res-01"}},
    }


class _NoopPublisher:
    async def publish(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN201, ARG002
        raise AssertionError("publisher MUST NOT be invoked on an abstain path")


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag": "owner"},
        cited_rule_ids=("r1",),
        confidence_signals={"a": 0.8, "b": 0.9},
    )


class _Proposer:
    def __init__(self, candidate: QualityCandidate | None) -> None:
        self._candidate = candidate

    async def propose(self, *, event: Event) -> QualityCandidate | None:
        del event
        return self._candidate


class _FakeGate:
    def __init__(self, outcome: QualityOutcome) -> None:
        self._outcome = outcome

    async def evaluate(self, candidate: QualityCandidate) -> QualityDecision:
        return QualityDecision(outcome=self._outcome, candidate=candidate)


def _make_loop(
    *,
    t2_engine: T2Tier | None,
    audit: InMemoryStateStore,
    tmp_path: Path,
) -> ControlLoop:
    index = RuleIndex.build(rules=[])
    return ControlLoop(
        event_ingest=EventIngest(validator=_validator()),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index),
        action_builder=ActionBuilder(action_types_by_name={}),
        executor=ShadowExecutor(
            publisher=_NoopPublisher(),
            audit_store=audit,
            renderer=TemplateRenderer(remediation_root=tmp_path),
            resource_lock=ResourceLockManager(),
        ),
        audit_store=audit,
        rules_by_id={},
        t2_engine=t2_engine,
    )


def _routing() -> RoutingDecision:
    return RoutingDecision(
        tier=RoutingTier.T0,
        resource_type="compute.vm.novel",
        candidate_rule_ids=("r1",),
        reason=None,
    )


async def _ingest(idempotency: str) -> Event:
    event = EventIngest(validator=_validator()).ingest(_event_dict(idempotency))
    assert event is not None
    return event


# ---------------------------------------------------------------------------
# Backward compat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_absent_t2_engine_preserves_existing_abstain_flow(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(t2_engine=None, audit=audit, tmp_path=tmp_path)
    result = await loop.process(_event_dict("evt-t2-1"))
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert result.t2_decision is None
    kinds = {row["entry"].get("action_kind") for row in audit.audit_entries}
    assert "control_loop.t2_evaluate" not in kinds


@pytest.mark.asyncio
async def test_consult_t2_absent_engine_returns_none(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(t2_engine=None, audit=audit, tmp_path=tmp_path)
    event = await _ingest("evt-t2-none")
    result = await loop._consult_t2(  # noqa: SLF001 - test hook
        event=event,
        decision=_routing(),
        citing=(),
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )
    assert result is None


# ---------------------------------------------------------------------------
# _consult_t2 maps + audits (shadow-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_t2_proposed_logs_shadow_only(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=_FakeGate(QualityOutcome.ELIGIBLE))
    loop = _make_loop(t2_engine=tier, audit=audit, tmp_path=tmp_path)
    event = await _ingest("evt-t2-proposed")
    result = await loop._consult_t2(  # noqa: SLF001 - test hook
        event=event,
        decision=_routing(),
        citing=("r1",),
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )
    assert result is not None
    assert result.outcome is ControlLoopOutcome.T2_PROPOSED_LOGGED
    assert result.tier == "t2"
    # Shadow-only: nothing executed, so the audit decision stays abstain.
    assert result.decision == "abstain"
    assert result.execution_results == ()
    assert result.t2_decision is not None
    assert result.t2_decision.outcome is T2Outcome.PROPOSED

    rows = [
        r["entry"]
        for r in audit.audit_entries
        if r["entry"].get("action_kind") == "control_loop.t2_evaluate"
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["mode"] == Mode.SHADOW.value
    assert row["stage"] == "t2_reasoning"
    assert row["t2_outcome"] == "proposed"
    assert row["t2_candidate"]["action_type"] == "remediate.tag-add"
    assert row["t2_quality"]["quality_outcome"] == "eligible"


@pytest.mark.asyncio
async def test_consult_t2_denied_maps(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=_FakeGate(QualityOutcome.DENY))
    loop = _make_loop(t2_engine=tier, audit=audit, tmp_path=tmp_path)
    event = await _ingest("evt-t2-deny")
    result = await loop._consult_t2(  # noqa: SLF001 - test hook
        event=event,
        decision=_routing(),
        citing=("r1",),
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )
    assert result is not None
    assert result.outcome is ControlLoopOutcome.T2_DENIED


@pytest.mark.asyncio
async def test_consult_t2_proposer_abstain_maps(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    tier = T2Tier(proposer=_Proposer(None), quality_gate=_FakeGate(QualityOutcome.ELIGIBLE))
    loop = _make_loop(t2_engine=tier, audit=audit, tmp_path=tmp_path)
    event = await _ingest("evt-t2-abstain")
    result = await loop._consult_t2(  # noqa: SLF001 - test hook
        event=event,
        decision=_routing(),
        citing=(),
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )
    assert result is not None
    assert result.outcome is ControlLoopOutcome.T2_ABSTAINED
    rows = [
        r["entry"]
        for r in audit.audit_entries
        if r["entry"].get("action_kind") == "control_loop.t2_evaluate"
    ]
    assert rows[0]["t2_candidate"] is None
