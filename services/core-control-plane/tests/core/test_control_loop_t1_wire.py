"""ControlLoop T1 wire test.

Covers the scope-expansion.md § 3.7 wiring: when ``t1_engine`` is
supplied, a T0 abstain routes through T1 for a shadow-only reuse log.
T1's reuse verdict does NOT execute in P1 (the
:attr:`requires_reverification` invariant on
:class:`~fdai.core.tiers.t1_lightweight.tier.T1Decision` still gates
execution through the verifier + risk gate, which lands in P2).

The tests are minimal by design: the T1 tier itself is unit-tested in
``services/core-control-plane/tests/core/tiers/t1_lightweight/``. What matters here is the WIRE:

- ``t1_engine=None`` -> loop behaves exactly as before (regression-free).
- ``_write_t1_audit`` produces the documented audit row shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.assurance_twin import DynamicRuntimeResult
from fdai.core.control_loop import ControlLoop, ControlLoopOutcome
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import RuleIndex, T0Engine
from fdai.core.tiers.t1_lightweight import CurrentReuseVerification
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    SimilarityMatch,
    T1Decision,
    T1Outcome,
    T1Tier,
)
from fdai.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Mode
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
        "payload": {
            "resource": {"type": "compute.vm.novel", "id": "res-01"},
        },
    }


class _NoopPublisher:
    """PR publisher that MUST NOT be invoked (T0 abstain path only)."""

    async def publish(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN201, ARG002
        raise AssertionError("publisher MUST NOT be invoked on an abstain path")


def _make_executor(audit: InMemoryStateStore, tmp_path: Path) -> ShadowExecutor:
    return ShadowExecutor(
        publisher=_NoopPublisher(),
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=tmp_path),
        resource_lock=ResourceLockManager(),
    )


def _current_verification() -> CurrentReuseVerification:
    return CurrentReuseVerification(
        case_ref=f"case-history:case-a:1:{'a' * 64}",
        observed_at=datetime.now(tz=UTC),
        evidence_refs=("b" * 64,),
        failure_fingerprint="c" * 64,
        resource_type="compute.vm.novel",
        topology_role="hosts",
        graph_digest="d" * 64,
        owner_digest="e" * 64,
        preconditions_passed=True,
        target_identity_verified=True,
        blast_radius_within_limit=True,
        policy_allowed=True,
        dry_run_passed=True,
        idempotency_available=True,
        rollback_resolved=True,
    )


def _make_loop(
    *,
    t1_engine: T1Tier | None,
    audit: InMemoryStateStore,
    tmp_path: Path,
    dynamic_runtime_coordinator=None,  # type: ignore[no-untyped-def]
    graph_dynamic_runtime_coordinator=None,  # type: ignore[no-untyped-def]
    event_correlator=None,  # type: ignore[no-untyped-def]
    causal_runtime_coordinator=None,  # type: ignore[no-untyped-def]
) -> ControlLoop:
    # Empty rule catalog -> trust-router abstains. The absent-T1 test
    # validates that path is untouched by the new seam.
    index = RuleIndex.build(rules=[])
    return ControlLoop(
        event_ingest=EventIngest(validator=_validator()),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index),
        action_builder=ActionBuilder(action_types_by_name={}),
        executor=_make_executor(audit, tmp_path),
        audit_store=audit,
        rules_by_id={},
        t1_engine=t1_engine,
        dynamic_runtime_coordinator=dynamic_runtime_coordinator,
        graph_dynamic_runtime_coordinator=graph_dynamic_runtime_coordinator,
        event_correlator=event_correlator,
        causal_runtime_coordinator=causal_runtime_coordinator,
    )


def _configure_t1_routing(loop: ControlLoop) -> None:
    action_types = load_action_type_catalog(
        Path(__file__).resolve().parents[2] / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
    )
    loop._action_builder = ActionBuilder(  # noqa: SLF001 - composition assertion
        action_types_by_name={item.name: item for item in action_types}
    )
    loop._rules_by_id = {  # type: ignore[assignment]  # noqa: SLF001
        "r1": SimpleNamespace(id="r1", remediates="remediate.tag-add")
    }


async def test_verified_t1_reuse_routes_through_unified_risk_gate(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(t1_engine=None, audit=audit, tmp_path=tmp_path)
    _configure_t1_routing(loop)
    loop._risk_table = SimpleNamespace()  # type: ignore[assignment]  # noqa: SLF001
    loop._risk_gate = SimpleNamespace()  # type: ignore[assignment]  # noqa: SLF001
    risk_decision = SimpleNamespace(
        is_auto=False,
        requires_hil=True,
        is_denied=False,
        decision="hil",
        gate=SimpleNamespace(effective_mode=Mode.SHADOW),
    )
    evaluate = AsyncMock(return_value=risk_decision)
    loop._evaluate_and_audit = evaluate  # type: ignore[method-assign]
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-t1-route"))
    assert event is not None
    learned = LearnedAction(
        signature="sig-route",
        rule_id="r1",
        action_type="remediate.tag-add",
        params={},
        incident_id="incident-1",
        success_rate=0.99,
        reuse_count=50,
    )
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.8,
        best_match=SimilarityMatch(action=learned, score=0.95),
        current_reuse_verification=_current_verification(),
    )

    result = await loop._route_t1_reuse(  # noqa: SLF001 - focused routing contract
        event=event,
        decision=RoutingDecision(
            tier=RoutingTier.T1,
            resource_type="compute.vm.novel",
        ),
        t1=t1,
        cs_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )

    assert result is not None
    assert result.outcome is ControlLoopOutcome.HIL
    assert result.decision == "hil"
    evaluate.assert_awaited_once()
    action = evaluate.await_args.kwargs["action"]
    assert action.action_type == "remediate.tag-add"
    assert action.target_resource_ref == "res-01"


async def test_verified_t1_reuse_without_risk_gate_records_hil_hold(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(t1_engine=None, audit=audit, tmp_path=tmp_path)
    _configure_t1_routing(loop)
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-t1-hold"))
    assert event is not None
    learned = LearnedAction(
        signature="sig-hold",
        rule_id="r1",
        action_type="remediate.tag-add",
        params={},
        incident_id="incident-1",
        success_rate=0.99,
        reuse_count=50,
    )
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.8,
        best_match=SimilarityMatch(action=learned, score=0.95),
        current_reuse_verification=_current_verification(),
    )

    result = await loop._route_t1_reuse(  # noqa: SLF001 - focused routing contract
        event=event,
        decision=RoutingDecision(tier=RoutingTier.T1, resource_type="compute.vm.novel"),
        t1=t1,
        cs_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )

    assert result is not None
    assert result.outcome is ControlLoopOutcome.HIL
    assert result.reason == "t1_risk_gate_unavailable"
    holds = [
        item["entry"]
        for item in audit.audit_entries
        if item["entry"].get("action_kind") == "control_loop.t1_routing_hold"
    ]
    assert len(holds) == 1


async def test_unverified_t1_reuse_never_reaches_risk_gate(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(t1_engine=None, audit=audit, tmp_path=tmp_path)
    evaluate = AsyncMock()
    loop._evaluate_and_audit = evaluate  # type: ignore[method-assign]
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-t1-unverified"))
    assert event is not None
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.8,
        best_match=SimilarityMatch(
            action=LearnedAction(
                signature="sig-unverified",
                rule_id="r1",
                action_type="remediate.tag-add",
                params={},
                incident_id="incident-1",
                success_rate=0.99,
                reuse_count=50,
            ),
            score=0.95,
        ),
    )

    result = await loop._route_t1_reuse(  # noqa: SLF001 - focused routing contract
        event=event,
        decision=RoutingDecision(tier=RoutingTier.T1, resource_type="compute.vm.novel"),
        t1=t1,
        cs_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )

    assert result is None
    evaluate.assert_not_awaited()


# ---------------------------------------------------------------------------
# Backward compat: absent t1_engine keeps existing abstain flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_absent_t1_engine_preserves_existing_abstain_flow(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(t1_engine=None, audit=audit, tmp_path=tmp_path)
    result = await loop.process(_event_dict("evt-key-1"))
    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert result.t1_decision is None
    # No `control_loop.t1_evaluate` audit row when T1 is absent.
    kinds = {row["entry"].get("action_kind") for row in audit.audit_entries}
    assert "control_loop.t1_evaluate" not in kinds


class _Correlator:
    def correlate(self, event):  # type: ignore[no-untyped-def]
        return SimpleNamespace(correlated=True, incident_id="incident-novel")


class _CausalRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze(self, *, event, incident_id):  # type: ignore[no-untyped-def]
        from fdai.core.rca import CausalRuntimeOutcome, CausalRuntimeResult

        self.calls.append(incident_id)
        return CausalRuntimeResult(CausalRuntimeOutcome.NO_EVIDENCE)


async def test_temporal_causality_observes_trust_router_abstain(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    causal = _CausalRuntime()
    loop = _make_loop(
        t1_engine=None,
        audit=audit,
        tmp_path=tmp_path,
        event_correlator=_Correlator(),
        causal_runtime_coordinator=causal,
    )

    result = await loop.process(_event_dict("evt-causal-novel"))

    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert causal.calls == ["incident-novel"]
    assert any(
        row["entry"].get("action_kind") == "rca.temporal_causality" for row in audit.audit_entries
    )


# ---------------------------------------------------------------------------
# _write_t1_audit produces the expected schema (unit test on the helper)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_t1_audit_records_the_full_verdict(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(dim=32),
        pattern_library=InMemoryPatternLibrary(),
    )
    loop = _make_loop(t1_engine=tier, audit=audit, tmp_path=tmp_path)
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-audit"))
    assert event is not None

    routing = RoutingDecision(
        tier=RoutingTier.T0,
        resource_type="compute.vm.novel",
        candidate_rule_ids=("some.rule",),
        reason=None,
    )
    learned = LearnedAction(
        signature="sig-1",
        rule_id="ops.legacy.restart",
        action_type="ops.restart-service",
        params={},
        incident_id="inc-01",
        success_rate=0.9,
    )
    best = SimilarityMatch(action=learned, score=0.87)
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=best,
        reason=None,
        reasons=(),
        current_reuse_verification=CurrentReuseVerification(
            case_ref=f"case-history:case-a:1:{'a' * 64}",
            observed_at=datetime.now(tz=UTC),
            evidence_refs=("b" * 64,),
            failure_fingerprint="c" * 64,
            resource_type="compute.vm.novel",
            topology_role="hosts",
            graph_digest="d" * 64,
            owner_digest="e" * 64,
            preconditions_passed=True,
            target_identity_verified=True,
            blast_radius_within_limit=True,
            policy_allowed=True,
            dry_run_passed=True,
            idempotency_available=True,
            rollback_resolved=True,
        ),
    )
    await loop._write_t1_audit(event=event, decision=routing, t1=t1)  # noqa: SLF001 - test hook

    rows = [row["entry"] for row in audit.audit_entries]
    assert len(rows) == 1
    row = rows[0]
    assert row["action_kind"] == "control_loop.t1_evaluate"
    assert row["mode"] == Mode.SHADOW.value
    assert row["stage"] == "t1_similarity"
    assert row["t1_outcome"] == "reused"
    assert row["t1_threshold"] == pytest.approx(0.7)
    assert row["t1_best_match"] == {
        "score": 0.87,
        "rule_id": "ops.legacy.restart",
        "action_type": "ops.restart-service",
        "success_rate": 0.9,
    }
    assert row["resource_type"] == "compute.vm.novel"
    verification = row["t1_current_reuse_verification"]
    assert verification["case_ref"].startswith("case-history:case-a")
    assert verification["evidence_refs"] == ["b" * 64]
    assert verification["policy_allowed"] is True


@pytest.mark.asyncio
async def test_write_t1_audit_handles_no_best_match(tmp_path: Path) -> None:
    """Abstain path: no neighbour -> best_match=None is legal in the audit row."""
    audit = InMemoryStateStore()
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(dim=32),
        pattern_library=InMemoryPatternLibrary(),
    )
    loop = _make_loop(t1_engine=tier, audit=audit, tmp_path=tmp_path)
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-abstain"))
    assert event is not None
    routing = RoutingDecision(
        tier=RoutingTier.T0,
        resource_type="compute.vm.novel",
        candidate_rule_ids=(),
        reason=None,
    )
    t1 = T1Decision(
        outcome=T1Outcome.ABSTAIN,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=None,
        reason="no_neighbour_found",
        reasons=("no_neighbour_found",),
    )
    await loop._write_t1_audit(event=event, decision=routing, t1=t1)  # noqa: SLF001

    row = [row["entry"] for row in audit.audit_entries][0]
    assert row["t1_outcome"] == "abstain"
    assert row["t1_best_match"] is None
    assert row["t1_reason"] == "no_neighbour_found"


class _DynamicCoordinator:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises

    async def simulate(self, *, event, action):  # type: ignore[no-untyped-def]
        if self.raises:
            raise RuntimeError("simulation unavailable")
        return DynamicRuntimeResult(None, "simulation_request_unavailable")


class _GraphDynamicCoordinator:
    async def simulate(self, *, event, action):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            reason="graph_simulation_completed",
            simulation=SimpleNamespace(
                active_trajectory=SimpleNamespace(digest="a" * 64),
                requires_review=False,
                reason_codes=(),
            ),
        )


class _PassingDynamicCoordinator:
    async def simulate(self, *, event, action):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            reason="simulation_completed",
            simulation=SimpleNamespace(
                simulation_id="simulation-1",
                requires_review=False,
                ordered_branch_ids=("branch-1",),
            ),
        )


class _FailingAudit:
    async def append_audit_entry(self, entry):  # type: ignore[no-untyped-def]
        raise RuntimeError("audit unavailable")


@pytest.mark.parametrize("raises", [False, True])
async def test_dynamic_simulation_is_shadow_audited_without_execution(
    tmp_path: Path,
    raises: bool,
) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(
        t1_engine=None,
        audit=audit,
        tmp_path=tmp_path,
        dynamic_runtime_coordinator=_DynamicCoordinator(raises=raises),
    )
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-dynamic"))
    assert event is not None
    learned = LearnedAction(
        signature="sig-1",
        rule_id="ops.legacy.restart",
        action_type="ops.restart-service",
        params={},
        incident_id="inc-01",
        success_rate=0.9,
    )
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=SimilarityMatch(action=learned, score=0.9),
    )

    await loop._simulate_and_audit_dynamic(event=event, t1=t1)  # noqa: SLF001

    row = audit.audit_entries[0]["entry"]
    assert row["action_kind"] == "dynamic.simulation"
    assert row["mode"] == "shadow"
    assert row["simulation_requires_review"] is True
    assert row["simulation_reason"] == (
        "simulation_failed:RuntimeError" if raises else "simulation_request_unavailable"
    )


async def test_successful_simulation_with_audit_failure_is_not_reclassified(
    tmp_path: Path,
    caplog,
) -> None:
    loop = _make_loop(
        t1_engine=None,
        audit=_FailingAudit(),  # type: ignore[arg-type]
        tmp_path=tmp_path,
        dynamic_runtime_coordinator=_DynamicCoordinator(raises=False),
    )
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-audit-failure"))
    assert event is not None
    learned = LearnedAction(
        signature="sig-1",
        rule_id="ops.legacy.restart",
        action_type="ops.restart-service",
        params={},
        incident_id="inc-01",
        success_rate=0.9,
    )
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=SimilarityMatch(action=learned, score=0.9),
    )

    await loop._simulate_and_audit_dynamic(event=event, t1=t1)  # noqa: SLF001

    record = next(
        item for item in caplog.records if item.message == "dynamic_simulation_audit_failed"
    )
    assert record.simulation_reason == "simulation_request_unavailable"


async def test_dynamic_simulation_and_audit_double_failure_is_isolated(tmp_path: Path) -> None:
    audit = _FailingAudit()
    loop = _make_loop(
        t1_engine=None,
        audit=audit,  # type: ignore[arg-type]
        tmp_path=tmp_path,
        dynamic_runtime_coordinator=_DynamicCoordinator(raises=True),
    )
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-double-failure"))
    assert event is not None
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=SimilarityMatch(
            action=LearnedAction(
                signature="sig-1",
                rule_id="ops.legacy.restart",
                action_type="ops.restart-service",
                params={},
                incident_id="inc-01",
                success_rate=0.9,
            ),
            score=0.9,
        ),
    )

    await loop._simulate_and_audit_dynamic(event=event, t1=t1)  # noqa: SLF001


async def test_dynamic_guard_passes_only_complete_audited_simulation(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(
        t1_engine=None,
        audit=audit,
        tmp_path=tmp_path,
        dynamic_runtime_coordinator=_PassingDynamicCoordinator(),
    )
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-dynamic-pass"))
    assert event is not None
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=SimilarityMatch(
            action=LearnedAction(
                signature="sig-pass",
                rule_id="r1",
                action_type="remediate.tag-add",
                params={},
                incident_id="inc-pass",
                success_rate=0.9,
            ),
            score=0.9,
        ),
    )

    decision = await loop._simulate_and_audit_dynamic(event=event, t1=t1)  # noqa: SLF001

    assert decision.configured is True
    assert decision.passed is True
    assert decision.reasons == ()


async def test_dynamic_guard_holds_when_decision_audit_fails(tmp_path: Path) -> None:
    loop = _make_loop(
        t1_engine=None,
        audit=_FailingAudit(),  # type: ignore[arg-type]
        tmp_path=tmp_path,
        dynamic_runtime_coordinator=_PassingDynamicCoordinator(),
    )
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-dynamic-audit-hold"))
    assert event is not None
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=SimilarityMatch(
            action=LearnedAction(
                signature="sig-audit-hold",
                rule_id="r1",
                action_type="remediate.tag-add",
                params={},
                incident_id="inc-audit-hold",
                success_rate=0.9,
            ),
            score=0.9,
        ),
    )

    decision = await loop._simulate_and_audit_dynamic(event=event, t1=t1)  # noqa: SLF001

    assert decision.passed is False
    assert decision.reasons == ("scalar_simulation_audit_failed",)


async def test_configured_dynamic_gap_holds_before_t1_risk_routing(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    learned = LearnedAction(
        signature="sig-route-hold",
        rule_id="r1",
        action_type="remediate.tag-add",
        params={},
        incident_id="inc-route-hold",
        success_rate=0.9,
    )
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id="event-route-hold",
        threshold=0.7,
        best_match=SimilarityMatch(action=learned, score=0.9),
        current_reuse_verification=_current_verification(),
    )
    engine = SimpleNamespace(evaluate=AsyncMock(return_value=t1))
    loop = _make_loop(
        t1_engine=engine,  # type: ignore[arg-type]
        audit=audit,
        tmp_path=tmp_path,
        dynamic_runtime_coordinator=_DynamicCoordinator(),
    )
    route = AsyncMock()
    loop._route_t1_reuse = route  # type: ignore[method-assign]
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-route-hold"))
    assert event is not None

    result = await loop._evaluate_fallback_tiers(  # noqa: SLF001
        event=event,
        decision=RoutingDecision(tier=RoutingTier.T1, resource_type="compute.vm.novel"),
        citing=(),
        cs_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )

    assert result is not None
    assert result.outcome is ControlLoopOutcome.HIL
    assert result.reason == "dynamic_guard:simulation_request_unavailable"
    route.assert_not_awaited()


async def test_graph_only_dynamic_simulation_is_shadow_audited(tmp_path: Path) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(
        t1_engine=None,
        audit=audit,
        tmp_path=tmp_path,
        graph_dynamic_runtime_coordinator=_GraphDynamicCoordinator(),
    )
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-graph-dynamic"))
    assert event is not None
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=SimilarityMatch(
            action=LearnedAction(
                signature="sig-graph",
                rule_id="ops.legacy.restart",
                action_type="ops.restart-service",
                params={},
                incident_id="inc-graph",
                success_rate=0.9,
            ),
            score=0.9,
        ),
    )

    await loop._simulate_and_audit_dynamic(event=event, t1=t1)  # noqa: SLF001

    row = audit.audit_entries[0]["entry"]
    assert row["action_kind"] == "dynamic.graph_simulation"
    assert row["mode"] == "shadow"
    assert row["trajectory_digest"] == "a" * 64
    assert row["simulation_requires_review"] is False


async def test_scalar_and_graph_dynamic_simulations_emit_separate_audits(
    tmp_path: Path,
) -> None:
    audit = InMemoryStateStore()
    loop = _make_loop(
        t1_engine=None,
        audit=audit,
        tmp_path=tmp_path,
        dynamic_runtime_coordinator=_DynamicCoordinator(),
        graph_dynamic_runtime_coordinator=_GraphDynamicCoordinator(),
    )
    event = EventIngest(validator=_validator()).ingest(_event_dict("evt-both-dynamic"))
    assert event is not None
    t1 = T1Decision(
        outcome=T1Outcome.REUSED,
        event_id=str(event.event_id),
        threshold=0.7,
        best_match=SimilarityMatch(
            action=LearnedAction(
                signature="sig-both",
                rule_id="ops.legacy.restart",
                action_type="ops.restart-service",
                params={},
                incident_id="inc-both",
                success_rate=0.9,
            ),
            score=0.9,
        ),
    )

    await loop._simulate_and_audit_dynamic(event=event, t1=t1)  # noqa: SLF001

    action_kinds = [item["entry"]["action_kind"] for item in audit.audit_entries]
    assert action_kinds == ["dynamic.simulation", "dynamic.graph_simulation"]
