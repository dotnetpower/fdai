from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    ScenarioPromotionEvidence,
    ScenarioPromotionLedger,
    ScenarioPromotionState,
)
from fdai.core.chaos.scenario_catalog import CatalogEntry, catalog_fingerprint
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.recovery import RecoveryProbeKind
from fdai.delivery.chaos.governed import GovernedChaosExecutionAdapter
from fdai.delivery.chaos.governed_bindings import (
    GOVERNED_CHAOS_ENTRY_POINT_GROUP,
    GOVERNED_CHAOS_ENTRY_POINT_NAME,
    GovernedChaosBindings,
)
from fdai.delivery.chaos.governed_claims import target_digest
from fdai.delivery.chaos.governed_records import CHAOS_ACTION_TYPE, governed_chaos_run_id
from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallRequest, ToolPreconditionError

from fdai_governed_chaos_provider.provider import (
    StateStoreChaosApprovalVerifier,
    StateStoreChaosRunPlanner,
    StateStoreRecoveryEvidenceCollector,
    StateStoreThorRecoveryDispatcher,
)

NOW = datetime(2026, 10, 2, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)
SCENARIO_ID = "chaos.test.pod-cpu-spike"
TARGET = "pod-a"
RUN_ID = governed_chaos_run_id("chaos-key-1", SCENARIO_ID, (TARGET,))
APPROVAL_REF = "approval:test"
TARGET_BINDING_ID = "scenario-lab:aks-pod-cpu-spike"
RECOVERY_PLAN_ID = "recovery-233f7a0882b67958dc41bb7adc402e83"


class Injector:
    def __init__(self) -> None:
        self.fault_type = "pod_cpu_spike"
        self.injected: list[str] = []
        self.stopped: list[str] = []

    def mutated_resources(self, *, target: str) -> tuple[str, ...]:
        return (target,)

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:
        self.stopped.append(target)


class Probe:
    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        return True


class DistributedLock(ResourceLockManager):
    distributed = True


class ContendedLock:
    distributed = True

    @asynccontextmanager
    async def acquire(self, _resource_id: str) -> AsyncIterator[None]:
        await asyncio.Event().wait()
        yield


class Registry:
    def __init__(self, *, promoted: bool = True) -> None:
        self._promoted = promoted

    def mode_of(self, _action_type: str) -> Mode:
        return Mode.ENFORCE if self._promoted else Mode.SHADOW


def test_entry_point_is_registered() -> None:
    matches = [
        item
        for item in entry_points(group=GOVERNED_CHAOS_ENTRY_POINT_GROUP)
        if item.name == GOVERNED_CHAOS_ENTRY_POINT_NAME
    ]

    assert [item.value for item in matches] == [
        "fdai_governed_chaos_provider:build_governed_chaos_bindings"
    ]


@pytest.mark.parametrize(
    ("fixture_overrides", "expected_detail"),
    [
        ({"promoted_scenario": False}, "scenario_not_promoted"),
        ({"promoted_actions": False}, "action_type_not_promoted"),
        ({"plan_overrides": {"stop_conditions_ready": False}}, "stop_conditions_unavailable"),
    ],
)
async def test_provider_bindings_deny_when_promotion_or_safeguard_is_missing(
    fixture_overrides: dict[str, Any],
    expected_detail: str,
) -> None:
    fixture = await _fixture(**fixture_overrides)

    receipt = await fixture.adapter.execute(_request())

    assert receipt.outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert receipt.detail is not None and expected_detail in receipt.detail
    assert fixture.injector.injected == []


async def test_provider_target_lock_contention_refuses_before_injection() -> None:
    fixture = await _fixture(lock=ContendedLock())

    with pytest.raises(ToolPreconditionError, match="logical-target lock"):
        await fixture.adapter.execute(_request())

    assert fixture.injector.injected == []


async def test_provider_idempotent_replay_does_not_reinject() -> None:
    fixture = await _fixture()

    first = await fixture.adapter.execute(_request())
    second = await fixture.adapter.execute(_request())

    assert first.outcome is ToolCallOutcome.SUCCEEDED
    assert second.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert second.detail == "replayed:recovered"
    assert fixture.injector.injected == [TARGET]


async def test_provider_rolls_back_when_stop_condition_fires() -> None:
    fixture = await _fixture(stop_event=True)

    receipt = await fixture.adapter.execute(_request())

    assert receipt.outcome is ToolCallOutcome.STOPPED
    assert receipt.rollback_succeeded is True
    assert fixture.injector.injected == [TARGET]
    assert fixture.injector.stopped == [TARGET]


async def test_provider_never_reports_success_from_dispatch_alone() -> None:
    fixture = await _fixture(recovery_evidence=False)

    receipt = await fixture.adapter.execute(_request())

    assert receipt.outcome is ToolCallOutcome.FAILED
    assert receipt.rollback_succeeded is False
    assert receipt.detail == "escalated:unscorable"


class Fixture:
    def __init__(
        self,
        *,
        adapter: GovernedChaosExecutionAdapter,
        injector: Injector,
    ) -> None:
        self.adapter = adapter
        self.injector = injector


async def _fixture(
    *,
    promoted_scenario: bool = True,
    promoted_actions: bool = True,
    plan_overrides: dict[str, Any] | None = None,
    lock: Any | None = None,
    stop_event: bool = False,
    recovery_evidence: bool = True,
) -> Fixture:
    store = InMemoryStateStore()
    entry = _entry()
    injector = Injector()
    factory = ScenarioFactory()
    factory.register_injector("test", lambda _entry, _context: injector)
    factory.register_probe("pod_restart", lambda _entry, _context: Probe())
    await _seed_approval(store)
    await _seed_plan(store, plan_overrides or {})
    await _seed_dispatch(store)
    if recovery_evidence:
        await _seed_recovery_evidence(store)
    if stop_event:
        await _seed_stop_event(store)
    bindings = GovernedChaosBindings(
        state_store=store,
        action_registry=Registry(promoted=promoted_actions),
        scenario_ledger=_ledger(entry, eligible=promoted_scenario),
        approval_verifier=StateStoreChaosApprovalVerifier(
            store=store,
            approval_prefix="approval:",
        ),
        planner=StateStoreChaosRunPlanner(
            store=store,
            plan_prefix="plan:",
            target_binding_id=TARGET_BINDING_ID,
            stop_event_prefix="stop:",
        ),
        recovery_dispatcher=StateStoreThorRecoveryDispatcher(
            store=store,
            dispatch_prefix="dispatch:",
        ),
        evidence_collector=StateStoreRecoveryEvidenceCollector(
            store=store,
            evidence_prefix="evidence:",
        ),
        target_lock=lock or DistributedLock(),
    )
    adapter = GovernedChaosExecutionAdapter(
        entries=(entry,),
        promoted_ids=frozenset({entry.id}),
        factory=factory,
        context={},
        bindings=bindings,
        action_type=_chaos_action_type(),
        clock=lambda: NOW,
        sleeper=_instant_sleep,
        lock_timeout_seconds=0.01,
    )
    return Fixture(adapter=adapter, injector=injector)


def _entry() -> CatalogEntry:
    return CatalogEntry(
        id=SCENARIO_ID,
        source_path=Path("pod-cpu-spike.yaml"),
        spec={
            "id": SCENARIO_ID,
            "version": 1,
            "fault_family": "pod_cpu_spike",
            "description": "bounded pod CPU spike",
            "target_type": "pod",
            "expected_signal": "pod_restart",
            "blast_radius_cap": 1,
            "duration_seconds": 1.0,
            "params": {},
            "rollback_note": "stop the pod CPU stress",
            "injector": "test:pod-cpu-spike",
        },
    )


def _request() -> ToolCallRequest:
    return ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000001207"),
        idempotency_key="chaos-key-1",
        action_type_name=CHAOS_ACTION_TYPE,
        rule_ids=(SCENARIO_ID,),
        tool_ref=SCENARIO_ID,
        arguments={"scenario_id": SCENARIO_ID, "targets": [TARGET]},
        labels=("enforce",),
        mode=Mode.ENFORCE,
        stop_conditions=tuple(_chaos_action_type().stop_conditions),
        metadata={"approval_ref": APPROVAL_REF, "tier": "t0"},
    )


def _ledger(entry: CatalogEntry, *, eligible: bool) -> ScenarioPromotionLedger:
    ledger = ScenarioPromotionLedger()
    if not eligible:
        return ledger
    key = ScenarioEvidenceKey(entry.id, 1, catalog_fingerprint([entry]))
    shadow = _evidence(
        "shadow",
        key,
        ScenarioPromotionState.COLLECTED,
        ScenarioPromotionState.SHADOW_VALIDATED,
    )
    pending = _evidence(
        "pending",
        key,
        ScenarioPromotionState.SHADOW_VALIDATED,
        ScenarioPromotionState.APPROVAL_PENDING,
    )
    approved = replace(
        _evidence(
            "approved",
            key,
            ScenarioPromotionState.APPROVAL_PENDING,
            ScenarioPromotionState.ENFORCE_ELIGIBLE,
        ),
        approval_ref="promotion-approval",
        approval_principal="Var",
    )
    for item in (shadow, pending, approved):
        ledger.append(item)
    return ledger


def _evidence(
    evidence_id: str,
    key: ScenarioEvidenceKey,
    from_state: ScenarioPromotionState,
    to_state: ScenarioPromotionState,
) -> ScenarioPromotionEvidence:
    return ScenarioPromotionEvidence(
        evidence_id=evidence_id,
        key=key,
        from_state=from_state,
        to_state=to_state,
        actor_principal="Saga" if to_state is ScenarioPromotionState.SHADOW_VALIDATED else "Mimir",
        audit_ref=f"audit:{evidence_id}",
        observed_at=NOW,
        runner_version="provider-test/1",
        stop_condition_observed=True,
        rollback_succeeded=True,
        blast_radius_compliant=True,
        detection_latency_ms=100,
        latency_budget_ms=500,
    )


async def _seed_approval(store: InMemoryStateStore) -> None:
    await store.write_state(
        f"approval:{APPROVAL_REF}",
        {
            "schema": "fdai.governed-chaos.approval",
            "schema_version": "1.0.0",
            "approval_ref": APPROVAL_REF,
            "approval_principal": "Var",
            "approver_ids": ["approver-a"],
            "initiator_id": "initiator-a",
            "intent": "enforce",
            "scenario_id": SCENARIO_ID,
            "run_id": RUN_ID,
            "target_digests": [target_digest(TARGET)],
            "expires_at": FUTURE.isoformat(),
        },
    )


async def _seed_plan(store: InMemoryStateStore, overrides: dict[str, Any]) -> None:
    record = {
        "schema": "fdai.governed-chaos.run-plan",
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "scenario_id": SCENARIO_ID,
        "targets": [TARGET],
        "target_binding_id": TARGET_BINDING_ID,
        "causal_hypothesis_ref": "hypothesis:pod-cpu-spike",
        "refutation_query_ref": "query:pod-cpu-spike",
        "owner_ref": "owner:scenario-lab",
        "dry_run_receipt": "dry-run:pod-cpu-spike",
        "supported_environment": True,
        "maintenance_window_active": True,
        "graph_complete": True,
        "objective_headroom": True,
        "recovery_ready": True,
        "telemetry_ready": True,
        "no_conflicting_work": True,
        "kill_switch_clear": True,
        "stop_conditions_ready": True,
        "production_or_stateful": False,
        "recovery_plan": _recovery_plan_record(),
    }
    record.update(overrides)
    await store.write_state(f"plan:{RUN_ID}", record)


def _recovery_plan_record() -> dict[str, Any]:
    return {
        "strategy": "state_forward",
        "workflow_ref": "recover-aks-pod-cpu-spike",
        "workflow_version": "1.0.0",
        "catalog_digest": "catalog-1",
        "impact_envelope_id": "impact-1",
        "recovery_objective_ref": "rto-1",
        "verification_probes": [kind.value for kind in RecoveryProbeKind],
        "direct_target_ids": [TARGET],
        "graph_revision": "graph-1",
        "dry_run_receipt": "dry-run:pod-cpu-spike",
        "last_rehearsed_at": NOW.isoformat(),
        "expires_at": FUTURE.isoformat(),
        "actions": [
            {
                "action_id": "restore",
                "action_type_ref": "ops.restore-service",
                "action_type_version": "1.0.0",
                "target_ref": TARGET,
                "depends_on": [],
                "compensation_action_type_ref": "ops.undo-restore",
                "stop_conditions": ["time_box"],
                "rollback_ref": "rollback:restore",
            }
        ],
    }


async def _seed_dispatch(store: InMemoryStateStore) -> None:
    await store.write_state(
        f"dispatch:{RECOVERY_PLAN_ID}:compensate:restore",
        {
            "schema": "fdai.governed-chaos.recovery-dispatch",
            "schema_version": "1.0.0",
            "action_id": "restore",
            "action_type_ref": "ops.restore-service",
            "target_ref": TARGET,
            "dispatcher_principal": "Thor",
            "receipt_ref": "thor:restore",
        },
    )


async def _seed_recovery_evidence(store: InMemoryStateStore) -> None:
    await store.write_state(
        f"evidence:{RECOVERY_PLAN_ID}",
        {
            "schema": "fdai.governed-chaos.recovery-evidence",
            "schema_version": "1.0.0",
            "plan_id": RECOVERY_PLAN_ID,
            "observer_principal": "Heimdall",
            "telemetry_complete": True,
            "probes": [
                {
                    "kind": kind.value,
                    "verdict": "passed",
                    "observed_at": NOW.isoformat(),
                    "evidence_ref": f"evidence:{kind.value}",
                }
                for kind in RecoveryProbeKind
            ],
        },
    )


async def _seed_stop_event(store: InMemoryStateStore) -> None:
    await store.write_state(
        f"stop:{RUN_ID}",
        {
            "schema": "fdai.governed-chaos.stop-event",
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "impact_envelope_id": "impact-1",
            "reason": "forbidden_signal",
            "observed_resources": [TARGET],
            "observed_signals": ["error_budget_burn"],
            "occurred_at": NOW.isoformat(),
            "detail": "forbidden signal observed",
        },
    )


async def _instant_sleep(_seconds: float) -> None:
    return None


def _chaos_action_type():
    path = (
        Path(__file__).resolve().parents[3]
        / "rule-catalog"
        / "action-types"
        / "tool.run-chaos-experiment.yaml"
    )
    return load_action_type_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8")),
        schema_registry=PackageResourceSchemaRegistry(),
    )
