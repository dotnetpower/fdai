"""ControlLoop T1 wire test.

Covers the scope-expansion.md § 3.7 wiring: when ``t1_engine`` is
supplied, a T0 abstain routes through T1 for a shadow-only reuse log.
T1's reuse verdict does NOT execute in P1 (the
:attr:`requires_reverification` invariant on
:class:`~fdai.core.tiers.t1_lightweight.tier.T1Decision` still gates
execution through the verifier + risk gate, which lands in P2).

The tests are minimal by design: the T1 tier itself is unit-tested in
``tests/core/tiers/t1_lightweight/``. What matters here is the WIRE:

- ``t1_engine=None`` -> loop behaves exactly as before (regression-free).
- ``_write_t1_audit`` produces the documented audit row shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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


def _make_loop(
    *,
    t1_engine: T1Tier | None,
    audit: InMemoryStateStore,
    tmp_path: Path,
    dynamic_runtime_coordinator=None,  # type: ignore[no-untyped-def]
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
        event_correlator=event_correlator,
        causal_runtime_coordinator=causal_runtime_coordinator,
    )


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
        "simulation_failed" if raises else "simulation_request_unavailable"
    )


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
