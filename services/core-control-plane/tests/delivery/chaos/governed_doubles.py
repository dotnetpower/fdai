"""Shared doubles for the governed chaos adapter tests.

Every collaborator is an in-memory fake: no injector, network, or cloud call.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai.core.chaos.contract import FaultScenario
from fdai.core.chaos.guard import ChaosStopEvent, ChaosStopReason
from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    ScenarioPromotionEvidence,
    ScenarioPromotionLedger,
    ScenarioPromotionState,
)
from fdai.core.chaos.scenario_catalog import CatalogEntry, catalog_fingerprint
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.recovery import (
    ProbeVerdict,
    RecoveryAction,
    RecoveryPlanRecord,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryStrategy,
    compile_recovery_plan,
)
from fdai.delivery.chaos.governed_bindings import ChaosApprovalEvidence, ChaosRunPlan
from fdai.delivery.chaos.governed_records import governed_chaos_run_id
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import ToolCallRequest

NOW = datetime(2026, 7, 31, tzinfo=UTC)
SCENARIO_ID = "chaos.test.pod-kill"
ENTRY = CatalogEntry(
    id=SCENARIO_ID,
    source_path=Path("pod-kill.yaml"),
    spec={
        "id": SCENARIO_ID,
        "version": 1,
        "fault_family": "pod_kill",
        "description": "bounded pod kill",
        "target_type": "pod",
        "expected_signal": "pod_restart",
        "blast_radius_cap": 1,
        "duration_seconds": 1.0,
        "params": {},
        "rollback_note": "restart the pod",
        "injector": "test:pod-kill",
    },
)
ENFORCED = frozenset({"tool.run-chaos-experiment", "ops.restore-service", "ops.undo-restore"})
APPROVAL = ChaosApprovalEvidence(
    approval_ref="approval-1",
    approval_principal="Var",
    approver_ids=("approver-a",),
    initiator_id="initiator-a",
)
RUN_ID = governed_chaos_run_id("chaos-key-1", SCENARIO_ID, ("pod-a",))


class Injector:
    """A fake live injector that declares its mutation scope like factory builds."""

    def __init__(
        self,
        *,
        stop_fails: bool = False,
        inject_fails: bool = False,
        applied_then_timeout: bool = False,
        scope: tuple[str, ...] | None = None,
        fault_type: str = "pod_kill",
    ) -> None:
        self.fault_type = fault_type
        self.injected: list[str] = []
        self.stopped: list[str] = []
        self.live = asyncio.Event()
        self._stop_fails = stop_fails
        self._inject_fails = inject_fails
        self._applied_then_timeout = applied_then_timeout
        self._scope = scope

    def mutated_resources(self, *, target: str) -> tuple[str, ...]:
        return self._scope if self._scope is not None else (target,)

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        if self._inject_fails:
            raise RuntimeError("injector backend unavailable")
        self.injected.append(target)
        self.live.set()
        if self._applied_then_timeout:
            raise TimeoutError("the provider accepted the change but the client timed out")

    async def stop(self, *, target: str) -> None:
        self.stopped.append(target)
        if self._stop_fails:
            raise RuntimeError("rollback backend unavailable")


class UnscopedInjector(Injector):
    """A live injector that cannot name what it mutates."""

    mutated_resources = None  # type: ignore[assignment]


class Probe:
    def __init__(self, *, detects: bool = True) -> None:
        self._detects = detects

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        return self._detects


class DistributedLock(ResourceLockManager):
    """The in-process lock declared distributed, as a multi-replica provider would be."""

    distributed = True


class LostLock:
    """A distributed lock whose ownership was lost: it excludes nothing."""

    distributed = True

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        yield


class Registry:
    def __init__(self, enforced: frozenset[str]) -> None:
        self._enforced = enforced

    def mode_of(self, action_type: str) -> Mode:
        return Mode.ENFORCE if action_type in self._enforced else Mode.SHADOW

    def record(self, action_type: str) -> None:
        return None


class Verifier:
    def __init__(
        self,
        evidence: ChaosApprovalEvidence | None,
        *,
        closure: ChaosApprovalEvidence | None = None,
    ) -> None:
        self.evidence = evidence
        self.closure = closure
        self.calls = 0
        self.closure_requests: list[ToolCallRequest] = []

    async def verify(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
    ) -> ChaosApprovalEvidence | None:
        self.calls += 1
        return self.evidence

    async def verify_closure(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
    ) -> ChaosApprovalEvidence | None:
        self.closure_requests.append(request)
        return self.closure


class Planner:
    def __init__(self, plan: ChaosRunPlan | None, *, raises: bool = False) -> None:
        self._plan = plan
        self._raises = raises
        self.calls = 0

    async def plan(
        self,
        *,
        run_id: str,
        scenario: FaultScenario,
        targets: tuple[str, ...],
    ) -> ChaosRunPlan | None:
        self.calls += 1
        if self._raises:
            raise RuntimeError("inventory unavailable")
        return self._plan


class Dispatcher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def dispatch(self, action: RecoveryAction, *, idempotency_key: str) -> str | None:
        self.calls.append(action.action_id)
        return None if self.fail else f"receipt:{idempotency_key}"


class EvidenceCollector:
    def __init__(self, *, omit: RecoveryProbeKind | None = None) -> None:
        self.omit = omit

    async def collect(
        self,
        _plan: RecoveryPlanRecord,
    ) -> tuple[tuple[RecoveryProbeResult, ...], bool]:
        return (
            tuple(
                RecoveryProbeResult(
                    kind=kind,
                    verdict=ProbeVerdict.PASSED,
                    observed_at=NOW,
                    evidence_ref=f"evidence:{kind.value}",
                )
                for kind in RecoveryProbeKind
                if kind is not self.omit
            ),
            True,
        )


async def instant_sleep(_seconds: float) -> None:
    return None


async def blocking_sleep(_seconds: float) -> None:
    await asyncio.Event().wait()


async def no_stop(_elapsed: float) -> ChaosStopEvent | None:
    return None


async def forbidden_signal(_elapsed: float) -> ChaosStopEvent | None:
    return ChaosStopEvent(
        run_id=RUN_ID,
        impact_envelope_id="impact-1",
        reason=ChaosStopReason.FORBIDDEN_SIGNAL,
        observed_resources=("pod-a",),
        observed_signals=("error_budget_burn",),
        occurred_at=NOW,
        detail="forbidden signal observed",
    )


def recovery_plan(*, expires_at: datetime | None = None) -> RecoveryPlanRecord:
    return compile_recovery_plan(
        strategy=RecoveryStrategy.STATE_FORWARD,
        workflow_ref="recover-service",
        workflow_version="1.0.0",
        catalog_digest="catalog-1",
        actions=(
            RecoveryAction(
                action_id="restore",
                action_type_ref="ops.restore-service",
                action_type_version="1.0.0",
                target_ref="resource-a",
                compensation_action_type_ref="ops.undo-restore",
                stop_conditions=("time_box",),
                rollback_ref="rollback:restore",
            ),
        ),
        impact_envelope_id="impact-1",
        recovery_objective_ref="rto-1",
        verification_probes=("health",),
        direct_target_ids=("resource-a",),
        graph_revision="graph-1",
        dry_run_receipt="dry-run-1",
        last_rehearsed_at=NOW - timedelta(hours=2),
        expires_at=expires_at or NOW + timedelta(hours=1),
    )


def run_plan(**overrides: Any) -> ChaosRunPlan:
    values: dict[str, Any] = {
        "recovery_plan": recovery_plan(),
        "impact_guard": no_stop,
        "causal_hypothesis_ref": "hypothesis-1",
        "refutation_query_ref": "query-1",
        "owner_ref": "owner-1",
        "dry_run_receipt": "dry-run-1",
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
    }
    values.update(overrides)
    return ChaosRunPlan(**values)


def ledger(*, eligible: bool = True, entry: CatalogEntry = ENTRY) -> ScenarioPromotionLedger:
    """Return append-only scenario evidence that reaches ``enforce_eligible``."""

    evidence = ScenarioPromotionLedger()
    if not eligible:
        return evidence
    key = ScenarioEvidenceKey(entry.id, 1, catalog_fingerprint([entry]))
    state = ScenarioPromotionState
    shadow = {
        "stop_condition_observed": True,
        "rollback_succeeded": True,
        "blast_radius_compliant": True,
        "detection_latency_ms": 100,
        "latency_budget_ms": 500,
    }
    approval = {"approval_ref": "promotion-approval-1", "approval_principal": "Var"}
    steps: tuple[tuple[ScenarioPromotionState, ScenarioPromotionState, str, dict[str, Any]], ...]
    steps = (
        (state.COLLECTED, state.SHADOW_VALIDATED, "Saga", shadow),
        (state.SHADOW_VALIDATED, state.APPROVAL_PENDING, "Mimir", {}),
        (state.APPROVAL_PENDING, state.ENFORCE_ELIGIBLE, "Mimir", approval),
    )
    for from_state, to_state, actor, extra in steps:
        evidence.append(
            ScenarioPromotionEvidence(
                evidence_id=to_state.value,
                key=key,
                from_state=from_state,
                to_state=to_state,
                actor_principal=actor,
                audit_ref=f"audit:{to_state.value}",
                observed_at=NOW,
                runner_version="runner/1",
                **extra,
            )
        )
    return evidence
