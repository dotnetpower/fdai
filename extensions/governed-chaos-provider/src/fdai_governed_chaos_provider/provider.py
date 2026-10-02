"""State-backed collaborators for the governed Chaos scenario-lab provider."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.chaos.contract import FaultScenario
from fdai.core.chaos.guard import ChaosStopEvent, ChaosStopReason, ImpactGuard
from fdai.core.recovery import (
    ProbeVerdict,
    RecoveryAction,
    RecoveryPlanRecord,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryStrategy,
    compile_recovery_plan,
)
from fdai.delivery.chaos.governed_bindings import (
    CHAOS_CLOSURE_INTENT,
    CHAOS_ENFORCE_INTENT,
    ChaosApprovalEvidence,
    ChaosRunPlan,
)
from fdai.delivery.chaos.governed_claims import target_digest
from fdai.delivery.chaos.governed_records import CHAOS_ACTION_TYPE
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.tool import ToolCallRequest


class StateStoreChaosApprovalVerifier:
    """Verify Var approvals from durable state instead of trusting request metadata."""

    def __init__(self, *, store: StateStore, approval_prefix: str) -> None:
        self._store = store
        self._prefix = approval_prefix

    async def verify(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
    ) -> ChaosApprovalEvidence | None:
        return await self._verify(request, run_id=run_id, intent=CHAOS_ENFORCE_INTENT)

    async def verify_closure(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
    ) -> ChaosApprovalEvidence | None:
        return await self._verify(request, run_id=run_id, intent=CHAOS_CLOSURE_INTENT)

    async def _verify(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
        intent: str,
    ) -> ChaosApprovalEvidence | None:
        approval_ref = _metadata_text(request, "approval_ref")
        if approval_ref is None:
            return None
        raw = await self._store.read_state(f"{self._prefix}{approval_ref}")
        if raw is None:
            return None
        try:
            return _approval_from_record(raw, request, run_id=run_id, intent=intent)
        except (TypeError, ValueError, KeyError):
            return None


class AsyncActionModeRefresh(Protocol):
    async def refresh(self, action_type: str) -> None: ...


class StateStoreChaosRunPlanner:
    """Load the prepared run plan for one exact scenario-lab target binding."""

    def __init__(
        self,
        *,
        store: StateStore,
        action_registry: AsyncActionModeRefresh | None = None,
        plan_prefix: str,
        target_binding_id: str,
        stop_event_prefix: str,
    ) -> None:
        self._store = store
        self._action_registry = action_registry
        self._plan_prefix = plan_prefix
        self._target_binding_id = target_binding_id
        self._stop_event_prefix = stop_event_prefix

    async def plan(
        self,
        *,
        run_id: str,
        scenario: FaultScenario,
        targets: tuple[str, ...],
    ) -> ChaosRunPlan | None:
        raw = await self._store.read_state(f"{self._plan_prefix}{run_id}")
        if raw is None:
            return None
        try:
            plan = _run_plan_from_record(
                raw,
                run_id=run_id,
                scenario=scenario,
                targets=targets,
                target_binding_id=self._target_binding_id,
                guard=self._guard(run_id),
            )
            await self._refresh_action_modes(plan)
            return plan
        except (TypeError, ValueError, KeyError):
            return None

    def _guard(self, run_id: str) -> ImpactGuard:
        async def guard(_elapsed_seconds: float) -> ChaosStopEvent | None:
            raw = await self._store.read_state(f"{self._stop_event_prefix}{run_id}")
            if raw is None:
                return None
            return _stop_event_from_record(raw, run_id=run_id)

        return guard

    async def _refresh_action_modes(self, plan: ChaosRunPlan) -> None:
        if self._action_registry is None:
            return
        names = {CHAOS_ACTION_TYPE}
        for action in plan.recovery_plan.actions:
            names.add(action.action_type_ref)
            if action.compensation_action_type_ref:
                names.add(action.compensation_action_type_ref)
        for name in sorted(names):
            await self._action_registry.refresh(name)


class StateStoreThorRecoveryDispatcher:
    """Return only Thor-authored recovery dispatch receipts already retained in state."""

    def __init__(self, *, store: StateStore, dispatch_prefix: str) -> None:
        self._store = store
        self._prefix = dispatch_prefix

    async def dispatch(self, action: RecoveryAction, *, idempotency_key: str) -> str | None:
        raw = await self._store.read_state(f"{self._prefix}{idempotency_key}")
        if raw is None:
            return None
        try:
            _require_schema(raw, "fdai.governed-chaos.recovery-dispatch", "1.0.0")
            if raw.get("action_id") != action.action_id:
                return None
            if raw.get("action_type_ref") != action.action_type_ref:
                return None
            if raw.get("target_ref") != action.target_ref:
                return None
            if raw.get("dispatcher_principal") != "Thor":
                return None
            receipt_ref = _text(raw, "receipt_ref", max_length=512)
        except (TypeError, ValueError, KeyError):
            return None
        return receipt_ref


class StateStoreRecoveryEvidenceCollector:
    """Collect Heimdall recovery observations retained after the recovery action."""

    def __init__(self, *, store: StateStore, evidence_prefix: str) -> None:
        self._store = store
        self._prefix = evidence_prefix

    async def collect(
        self,
        plan: RecoveryPlanRecord,
    ) -> tuple[tuple[RecoveryProbeResult, ...], bool]:
        raw = await self._store.read_state(f"{self._prefix}{plan.plan_id}")
        if raw is None:
            return (), False
        try:
            _require_schema(raw, "fdai.governed-chaos.recovery-evidence", "1.0.0")
            if raw.get("plan_id") != plan.plan_id:
                return (), False
            if raw.get("observer_principal") != "Heimdall":
                return (), False
            telemetry_complete = _bool(raw, "telemetry_complete")
            probes = _probe_results(raw.get("probes"))
        except (TypeError, ValueError, KeyError):
            return (), False
        return probes, telemetry_complete


def _approval_from_record(
    raw: Mapping[str, Any],
    request: ToolCallRequest,
    *,
    run_id: str,
    intent: str,
) -> ChaosApprovalEvidence | None:
    _require_schema(raw, "fdai.governed-chaos.approval", "1.0.0")
    approval_ref = _text(raw, "approval_ref", max_length=256)
    if approval_ref != _metadata_text(request, "approval_ref"):
        return None
    if raw.get("approval_principal") != "Var" or raw.get("intent") != intent:
        return None
    expires_at = _aware_datetime(raw, "expires_at")
    if expires_at <= datetime.now(UTC):
        return None
    scenario_id = raw.get("scenario_id")
    request_scenario = request.arguments.get("scenario_id")
    if scenario_id is not None and scenario_id != request_scenario:
        return None
    approved_run = raw.get("run_id")
    if approved_run is not None and approved_run != run_id:
        return None
    targets = _request_targets(request)
    approved_digests = _string_tuple(raw.get("target_digests"), field="target_digests")
    if approved_digests and set(approved_digests) != {target_digest(item) for item in targets}:
        return None
    approver_ids = _string_tuple(raw.get("approver_ids"), field="approver_ids")
    initiator_id = _text(raw, "initiator_id", max_length=200)
    return ChaosApprovalEvidence(
        approval_ref=approval_ref,
        approval_principal="Var",
        approver_ids=approver_ids,
        initiator_id=initiator_id,
        intent=intent,
        run_id=str(approved_run) if approved_run is not None else None,
        target_digests=approved_digests,
    )


def _run_plan_from_record(
    raw: Mapping[str, Any],
    *,
    run_id: str,
    scenario: FaultScenario,
    targets: tuple[str, ...],
    target_binding_id: str,
    guard: Any,
) -> ChaosRunPlan:
    _require_schema(raw, "fdai.governed-chaos.run-plan", "1.0.0")
    if raw.get("run_id") != run_id:
        raise ValueError("run id mismatch")
    if raw.get("scenario_id") != scenario.scenario_id:
        raise ValueError("scenario mismatch")
    if raw.get("targets") != list(targets):
        raise ValueError("target mismatch")
    if raw.get("target_binding_id") != target_binding_id:
        raise ValueError("target binding mismatch")
    recovery = _compile_recovery_plan(raw.get("recovery_plan"))
    return ChaosRunPlan(
        recovery_plan=recovery,
        impact_guard=guard,
        causal_hypothesis_ref=_text(raw, "causal_hypothesis_ref", max_length=512),
        refutation_query_ref=_text(raw, "refutation_query_ref", max_length=512),
        owner_ref=_text(raw, "owner_ref", max_length=512),
        dry_run_receipt=_text(raw, "dry_run_receipt", max_length=512),
        supported_environment=_bool(raw, "supported_environment"),
        maintenance_window_active=_bool(raw, "maintenance_window_active"),
        graph_complete=_bool(raw, "graph_complete"),
        objective_headroom=_bool(raw, "objective_headroom"),
        recovery_ready=_bool(raw, "recovery_ready"),
        telemetry_ready=_bool(raw, "telemetry_ready"),
        no_conflicting_work=_bool(raw, "no_conflicting_work"),
        kill_switch_clear=_bool(raw, "kill_switch_clear"),
        stop_conditions_ready=_bool(raw, "stop_conditions_ready"),
        production_or_stateful=_bool(raw, "production_or_stateful"),
    )


def _compile_recovery_plan(raw: object) -> RecoveryPlanRecord:
    if not isinstance(raw, Mapping):
        raise TypeError("recovery_plan must be a mapping")
    actions = []
    raw_actions = raw.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise ValueError("recovery actions must be a non-empty list")
    for item in raw_actions:
        if not isinstance(item, Mapping):
            raise TypeError("recovery action must be a mapping")
        actions.append(
            RecoveryAction(
                action_id=_text(item, "action_id", max_length=200),
                action_type_ref=_text(item, "action_type_ref", max_length=200),
                action_type_version=_text(item, "action_type_version", max_length=80),
                target_ref=_text(item, "target_ref", max_length=512),
                depends_on=_string_tuple(item.get("depends_on", ()), field="depends_on"),
                compensation_action_type_ref=_optional_text(
                    item.get("compensation_action_type_ref"),
                    field="compensation_action_type_ref",
                    max_length=200,
                ),
                stop_conditions=_string_tuple(
                    item.get("stop_conditions", ()),
                    field="stop_conditions",
                ),
                rollback_ref=_optional_text(
                    item.get("rollback_ref"),
                    field="rollback_ref",
                    max_length=512,
                ),
            )
        )
    return compile_recovery_plan(
        strategy=RecoveryStrategy(_text(raw, "strategy", max_length=80)),
        workflow_ref=_text(raw, "workflow_ref", max_length=200),
        workflow_version=_text(raw, "workflow_version", max_length=80),
        catalog_digest=_text(raw, "catalog_digest", max_length=128),
        actions=tuple(actions),
        impact_envelope_id=_text(raw, "impact_envelope_id", max_length=200),
        recovery_objective_ref=_text(raw, "recovery_objective_ref", max_length=200),
        verification_probes=_string_tuple(
            raw.get("verification_probes"),
            field="verification_probes",
        ),
        direct_target_ids=_string_tuple(raw.get("direct_target_ids"), field="direct_target_ids"),
        graph_revision=_text(raw, "graph_revision", max_length=200),
        dry_run_receipt=_text(raw, "dry_run_receipt", max_length=512),
        last_rehearsed_at=_aware_datetime(raw, "last_rehearsed_at"),
        expires_at=_aware_datetime(raw, "expires_at"),
    )


def _probe_results(raw: object) -> tuple[RecoveryProbeResult, ...]:
    if not isinstance(raw, list):
        raise TypeError("probes must be a list")
    results = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("probe must be a mapping")
        results.append(
            RecoveryProbeResult(
                kind=RecoveryProbeKind(_text(item, "kind", max_length=80)),
                verdict=ProbeVerdict(_text(item, "verdict", max_length=80)),
                observed_at=_aware_datetime(item, "observed_at"),
                evidence_ref=_text(item, "evidence_ref", max_length=512),
            )
        )
    return tuple(results)


def _stop_event_from_record(raw: Mapping[str, Any], *, run_id: str) -> ChaosStopEvent:
    _require_schema(raw, "fdai.governed-chaos.stop-event", "1.0.0")
    if raw.get("run_id") != run_id:
        raise ValueError("run id mismatch")
    return ChaosStopEvent(
        run_id=run_id,
        impact_envelope_id=_text(raw, "impact_envelope_id", max_length=200),
        reason=ChaosStopReason(_text(raw, "reason", max_length=80)),
        observed_resources=_string_tuple(raw.get("observed_resources"), field="observed_resources"),
        observed_signals=_string_tuple(raw.get("observed_signals"), field="observed_signals"),
        occurred_at=_aware_datetime(raw, "occurred_at"),
        detail=_text(raw, "detail", max_length=512),
    )


def _require_schema(raw: Mapping[str, Any], name: str, version: str) -> None:
    if raw.get("schema") != name or raw.get("schema_version") != version:
        raise ValueError("unsupported record schema")


def _metadata_text(request: ToolCallRequest, field: str) -> str | None:
    value = request.metadata.get(field)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _request_targets(request: ToolCallRequest) -> tuple[str, ...]:
    value = request.arguments.get("targets")
    if not isinstance(value, list) or not value:
        raise ValueError("targets must be a non-empty list")
    targets = tuple(str(item).strip() for item in value)
    if any(not item for item in targets):
        raise ValueError("targets must be non-empty")
    return targets


def _text(raw: Mapping[str, Any], field: str, *, max_length: int) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{field} must be a bounded non-empty string")
    return value.strip()


def _optional_text(value: object, *, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{field} must be null or a bounded non-empty string")
    return value.strip()


def _bool(raw: Mapping[str, Any], field: str) -> bool:
    value = raw[field]
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _aware_datetime(raw: Mapping[str, Any], field: str) -> datetime:
    value = _text(raw, field, max_length=80)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _string_tuple(raw: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        raise TypeError(f"{field} must be a string array")
    values = tuple(str(item).strip() for item in raw)
    if any(not item for item in values):
        raise ValueError(f"{field} must contain non-empty strings")
    return values


__all__ = [
    "StateStoreChaosApprovalVerifier",
    "StateStoreChaosRunPlanner",
    "StateStoreRecoveryEvidenceCollector",
    "StateStoreThorRecoveryDispatcher",
]
