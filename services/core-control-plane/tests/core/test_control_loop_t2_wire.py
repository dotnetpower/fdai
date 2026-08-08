"""ControlLoop T2 wire test.

Covers the scope-expansion.md § 3.7 wiring: when ``t2_engine`` is supplied, an
event that T0 (and T1, if wired) abstained on falls through to T2 for a
shadow-only reasoning log. T2's verdict does NOT execute in this wiring -
building an :class:`Action` from the eligible candidate and routing it through
the risk-gate is a separate P2/P3 step, mirroring the shadow-only T1 reuse log.

Minimal by design: the T2 tier itself is unit-tested in
``services/core-control-plane/tests/core/tiers/t2_reasoning/``. What matters here is the WIRE:

- ``t2_engine=None`` -> loop behaves exactly as before (regression-free).
- ``_consult_t2`` maps the gate verdict to a T2 outcome and writes the
  documented ``control_loop.t2_evaluate`` audit row without executing.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fdai.core.control_loop import ControlLoop, ControlLoopOutcome, ControlLoopResult
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
from fdai.core.tiers.t2_reasoning import (
    T2Decision,
    T2Outcome,
    T2ProposalContext,
    T2Tier,
)
from fdai.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Event, Mode, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
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
            "resource": {
                "type": "compute.vm.novel",
                "resource_id": "res-01",
            }
        },
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
        self.calls = 0

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        del context
        self.calls += 1
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
    stage_publisher=None,
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
        rules_by_id={"r1": _rule()},
        t2_engine=t2_engine,
        stage_publisher=stage_publisher,
    )


def _routing() -> RoutingDecision:
    return RoutingDecision(
        tier=RoutingTier.T0,
        resource_type="compute.vm.novel",
        candidate_rule_ids=("r1",),
        reason=None,
    )


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "r1",
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "config_drift",
            "resource_type": "compute.vm.novel",
            "check_logic": {"kind": "rego", "reference": "policies/example.rego"},
            "remediation": {"template_ref": "remediations/example"},
            "remediates": "remediate.tag-add",
            "provenance": {
                "source_url": "https://example.com/rules/r1",
                "resolved_ref": "0000000000000000000000000000000000000000",
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-05T00:00:00Z",
            },
        }
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


@pytest.mark.asyncio
async def test_consult_t2_without_grounding_rules_skips_proposer(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    proposer = _Proposer(_candidate())
    tier = T2Tier(proposer=proposer, quality_gate=_FakeGate(QualityOutcome.ELIGIBLE))
    loop = _make_loop(t2_engine=tier, audit=audit, tmp_path=tmp_path)
    event = await _ingest("evt-t2-no-grounding")
    decision = RoutingDecision(
        tier=RoutingTier.T0,
        resource_type="compute.vm.novel",
        candidate_rule_ids=("missing-rule",),
        reason="no exact rule",
    )

    result = await loop._consult_t2(  # noqa: SLF001 - test hook
        event=event,
        decision=decision,
        citing=(),
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )

    assert result is None
    assert proposer.calls == 0


# ---------------------------------------------------------------------------
# _consult_t2 maps + audits (shadow-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_t2_without_risk_gate_records_hil_hold(tmp_path: Path) -> None:
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
    assert result.outcome is ControlLoopOutcome.HIL
    assert result.tier == "t2"
    assert result.decision == "hil"
    assert result.reason == "t2_risk_gate_unavailable"
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
    assert row["t2_quality"]["outcome"] == "eligible"
    holds = [
        item["entry"]
        for item in audit.audit_entries
        if item["entry"].get("action_kind") == "control_loop.t2_routing_hold"
    ]
    assert len(holds) == 1
    assert holds[0]["reason"] == "t2_risk_gate_unavailable"


@pytest.mark.asyncio
async def test_consult_t2_routed_result_emits_terminal_audit_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = InMemoryStateStore()
    recorder = RecordingStagePublisher()
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=_FakeGate(QualityOutcome.ELIGIBLE))
    loop = _make_loop(
        t2_engine=tier,
        audit=audit,
        tmp_path=tmp_path,
        stage_publisher=recorder,
    )
    event = await _ingest("evt-t2-routed")
    routed = ControlLoopResult(
        outcome=ControlLoopOutcome.HIL,
        tier="t2",
        decision="hil",
        resource_type="compute.vm.novel",
        event_id=str(event.event_id),
    )

    async def _route(**kwargs):  # noqa: ANN003, ANN202
        del kwargs
        return routed

    monkeypatch.setattr(loop, "_route_t2_candidate", _route)
    result = await loop._consult_t2(  # noqa: SLF001 - test hook
        event=event,
        decision=_routing(),
        citing=("r1",),
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )

    assert result is routed
    terminal = recorder.by_stage(StageName.AUDIT)
    assert len(terminal) == 1
    assert terminal[0].phase is StagePhase.DONE
    assert terminal[0].detail["outcome"] == ControlLoopOutcome.HIL.value
    assert terminal[0].detail["decision"] == "hil"
    assert terminal[0].detail["mode"] == Mode.SHADOW.value


@pytest.mark.asyncio
async def test_t2_candidate_requires_execution_authorization(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(t2_engine=None, audit=audit, tmp_path=tmp_path)
    action_types = load_action_type_catalog(
        Path(__file__).resolve().parents[4] / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
    )
    loop._action_builder = ActionBuilder(  # noqa: SLF001 - composition assertion
        action_types_by_name={item.name: item for item in action_types}
    )

    class _ProhibitedAuthorization:
        def __init__(self) -> None:
            self.requests: list[ExecutionAuthorizationRequest] = []

        async def evaluate(
            self, request: ExecutionAuthorizationRequest
        ) -> ExecutionAuthorizationResult:
            self.requests.append(request)
            return ExecutionAuthorizationResult(
                status=ExecutionAuthorizationStatus.PROHIBITED,
                decision_digest="digest",
                evaluator_ref="test-authorization",
                reason_codes=("policy_prohibited",),
            )

    authorization = _ProhibitedAuthorization()
    loop._execution_authorization_evaluator = authorization  # noqa: SLF001
    loop._risk_table = object()  # type: ignore[assignment]  # noqa: SLF001
    loop._risk_gate = object()  # type: ignore[assignment]  # noqa: SLF001
    risk = AsyncMock(side_effect=AssertionError("risk gate MUST NOT run"))
    loop._evaluate_and_audit = risk  # type: ignore[method-assign]
    event = await _ingest("evt-t2-authorization")
    candidate = replace(_candidate(), params={})
    t2 = T2Decision(
        outcome=T2Outcome.PROPOSED,
        candidate=candidate,
        quality_decision=QualityDecision(
            outcome=QualityOutcome.ELIGIBLE,
            candidate=candidate,
        ),
        reason="eligible",
    )

    result = await loop._route_t2_candidate(  # noqa: SLF001 - focused routing contract
        event=event,
        decision=_routing(),
        t2=t2,
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )

    assert result is not None
    assert result.outcome is ControlLoopOutcome.DENIED
    assert result.reason == "execution_authorization:prohibited"
    assert len(authorization.requests) == 1
    risk.assert_not_awaited()


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
    assert result.decision == "deny"


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
    assert result.decision == "hil"
    rows = [
        r["entry"]
        for r in audit.audit_entries
        if r["entry"].get("action_kind") == "control_loop.t2_evaluate"
    ]
    assert rows[0]["t2_candidate"] is None
