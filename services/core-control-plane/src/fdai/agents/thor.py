"""Thor - Responder (Wave 3 behavior).

Thor dispatches verdicts. It enforces per-resource mutex, tracks
ActionRun state through the lifecycle, requests HIL approval via Var,
and triggers rollback via Vidar on failure.

Hard dependencies (per pantheon 4.3):
- Saga must be reachable (audit chain must accept appends) - degrades
  new mutations to shadow when absent.
- Vidar must be reachable - degrades new mutations to shadow when
  absent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from weakref import WeakValueDictionary

from fdai.agents._framework import (
    action_semantics,
    thor_introspection,
    thor_persistence,
    thor_preflight,
)
from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.advisory_verdicts import is_non_action_verdict
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult
from fdai.agents._framework.pantheon import _THOR
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.thor_action_run import (
    ActionRun,
    ActionRunStore,
)
from fdai.agents._framework.thor_development_authority import ThorDevelopmentAuthorityMixin
from fdai.agents._framework.thor_dispatch_runtime import (
    ThorDispatchMixin,
)
from fdai.agents._framework.thor_dispatch_runtime import (
    _positive_quorum as _positive_quorum,
)
from fdai.agents._framework.thor_effect_verification import ThorEffectVerificationMixin
from fdai.agents._framework.thor_locks import _ReentrantAsyncLock
from fdai.agents._framework.thor_recovery_runtime import ThorRecoveryMixin
from fdai.core.operational_context.test_context_dispatch import TestContextDispatchGuard
from fdai.shared.contracts.models import FullAuthorityDevelopmentProfile
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

_ActionPayload = dict[str, Any]
ActionExecutor = Callable[[_ActionPayload], Awaitable[bool]]
"""Callable that mutates the target and returns True on success."""

ExecutionAuditRecorder = Callable[["ActionRun"], Awaitable[str]]
"""Persist one Saga-owned pre-execution intent and return its receipt id."""

ApproverAuthorizer = Callable[[str, str], bool | Awaitable[bool]]
OwnerAuthorizer = Callable[[str], bool | Awaitable[bool]]


def _kpi_ratio(numerator: int, denominator: int, *, unit: str) -> dict[str, object]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "insufficient_sample",
            "numerator": numerator,
            "denominator": denominator,
            "unit": unit,
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


class Thor(
    ThorDevelopmentAuthorityMixin,
    ThorRecoveryMixin,
    ThorDispatchMixin,
    ThorEffectVerificationMixin,
    Agent,
):
    """Wave-3 Thor: dispatcher + per-resource mutex + lifecycle owner."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        executor: ActionExecutor | None = None,
        shadow_required: Callable[[], bool] | None = None,
        shadow_by_default: bool = False,
        saga_available: bool = True,
        vidar_available: bool = True,
        state_store: ActionRunStore | None = None,
        execution_audit_recorder: ExecutionAuditRecorder | None = None,
        require_execution_audit: bool = False,
        hil_timeout_seconds: int = 3_600,
        effect_verification_timeout_seconds: int = 3_600,
        executor_timeout_seconds: float = 300.0,
        execution_audit_timeout_seconds: float = 30.0,
        preflight_timeout_seconds: float = 5.0,
        preflight_receipt_ttl_seconds: int = 300,
        preflight_simulator: thor_preflight.ThorPreflightSimulator | None = None,
        clock: Callable[[], datetime] | None = None,
        execution_resource_lock: ResourceLock | None = None,
        require_execution_resource_lock: bool = False,
        action_semantics_catalog: action_semantics.ActionSemanticsCatalog | None = None,
        approval_state_store: StateStore | None = None,
        approver_authorizer: ApproverAuthorizer | None = None,
        owner_authorizer: OwnerAuthorizer | None = None,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_executor_principal: str | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
    ) -> None:
        if isinstance(hil_timeout_seconds, bool) or hil_timeout_seconds < 1:
            raise ValueError("hil_timeout_seconds MUST be a positive integer")
        if (
            isinstance(effect_verification_timeout_seconds, bool)
            or effect_verification_timeout_seconds < 1
        ):
            raise ValueError("effect_verification_timeout_seconds MUST be a positive integer")
        if executor_timeout_seconds <= 0:
            raise ValueError("executor_timeout_seconds MUST be > 0")
        if execution_audit_timeout_seconds <= 0:
            raise ValueError("execution_audit_timeout_seconds MUST be > 0")
        if preflight_timeout_seconds <= 0:
            raise ValueError("preflight_timeout_seconds MUST be > 0")
        if isinstance(preflight_receipt_ttl_seconds, bool) or preflight_receipt_ttl_seconds < 1:
            raise ValueError("preflight_receipt_ttl_seconds MUST be a positive integer")
        super().__init__(spec=_THOR)
        self.bus = bus
        self._executor = executor or _default_executor
        self._shadow_required = shadow_required or (lambda: False)
        self._shadow_by_default = shadow_by_default
        self._saga_available = saga_available
        self._vidar_available = vidar_available
        self._agent_availability: Callable[[], Iterable[str]] | None = None
        self._state_store = state_store
        self._execution_audit_recorder = execution_audit_recorder
        self._require_execution_audit = require_execution_audit or development_profile is not None
        self._hil_timeout_seconds = hil_timeout_seconds
        self._effect_verification_timeout_seconds = effect_verification_timeout_seconds
        self._executor_timeout_seconds = executor_timeout_seconds
        self._execution_audit_timeout_seconds = execution_audit_timeout_seconds
        self._preflight_timeout_seconds = preflight_timeout_seconds
        self._preflight_receipt_ttl_seconds = preflight_receipt_ttl_seconds
        self._preflight_simulator = preflight_simulator
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._execution_resource_lock = execution_resource_lock
        self._require_execution_resource_lock = (
            require_execution_resource_lock or development_profile is not None
        )
        self._action_semantics = action_semantics_catalog
        self._approval_state_store = approval_state_store
        self._approver_authorizer = approver_authorizer
        self._owner_authorizer = owner_authorizer
        self._initialize_development_authority(
            development_profile,
            development_executor_principal,
            development_binding_source,
        )
        self._test_context_dispatch_guard: TestContextDispatchGuard | None = None
        self.action_runs: dict[str, ActionRun] = {}
        self._idempotency_runs: dict[str, ActionRun] = {}
        self._resource_locks: set[str] = set()
        # FIFO-cap terminal history; active runs retain resource mutex and approval lookups.
        self._max_retained_runs = 10_000
        self._retry_strategy_cache: BoundedLruDict[str, dict[str, object]] = BoundedLruDict(8)
        self._dr_failover_contract_decisions: BoundedLruDict[
            str,
            dict[str, object],
        ] = BoundedLruDict(self._max_retained_runs)
        self._correlation_locks: WeakValueDictionary[str, _ReentrantAsyncLock] = (
            WeakValueDictionary()
        )
        self._resource_dispatch_locks: WeakValueDictionary[str, asyncio.Lock] = (
            WeakValueDictionary()
        )
        self._batch_rollup_attempts: dict[str, tuple[str, ...]] = {}
        self._batch_attempt_rollups: dict[str, str] = {}
        self._batch_rollup_targets: dict[str, tuple[str, ...]] = {}
        self._batch_rollup_verdicts: dict[str, dict[str, Any]] = {}
        if self._state_store is not None:
            self.set_state_store(self._state_store)

    def bind_test_context_dispatch_guard(self, guard: TestContextDispatchGuard) -> None:
        """Bind an authority-lowering context recheck before processing runtime events."""
        if self._test_context_dispatch_guard is not None:
            raise RuntimeError("test context dispatch guard is already bound")
        self._test_context_dispatch_guard = guard

    def set_executor(self, executor: ActionExecutor) -> None:
        """Bind the composition root's privileged action executor."""
        self._executor = executor

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def set_state_store(self, store: ActionRunStore) -> None:
        """Attach a durable ActionRun store (composition-root seam)."""
        set_clock = getattr(store, "set_clock", None)
        if callable(set_clock):
            set_clock(self._now)
        self._state_store = store

    def set_execution_audit_recorder(
        self,
        recorder: ExecutionAuditRecorder | None,
        *,
        required: bool,
    ) -> None:
        """Bind the durable Saga-owned intent recorder used before executor I/O."""

        self._execution_audit_recorder = recorder
        self._require_execution_audit = required or self._development_profile is not None

    def set_execution_resource_lock(
        self,
        resource_lock: ResourceLock | None,
        *,
        required: bool,
    ) -> None:
        """Bind the cross-replica mutation lock required by enforce mode."""

        self._execution_resource_lock = resource_lock
        self._require_execution_resource_lock = required or self._development_profile is not None

    def set_action_semantics(
        self,
        catalog: action_semantics.ActionSemanticsCatalog | None,
    ) -> None:
        """Bind ActionType-derived execution semantics for quorum rechecks."""

        self._action_semantics = catalog

    def set_preflight_simulator(
        self,
        simulator: thor_preflight.ThorPreflightSimulator | None,
    ) -> None:
        """Bind Thor's provider-neutral pre-flight simulator."""

        self._preflight_simulator = simulator

    def set_approval_readback(
        self,
        store: StateStore | None,
        *,
        approver_authorizer: ApproverAuthorizer | None,
        owner_authorizer: OwnerAuthorizer | None = None,
    ) -> None:
        """Bind Var durable approval readback for non-shadow HIL execution."""

        self._approval_state_store = store
        self._approver_authorizer = approver_authorizer
        self._owner_authorizer = owner_authorizer

    async def rehydrate(self) -> int:
        return await thor_persistence.rehydrate(self)

    async def _resume_rehydrated(self, run: ActionRun) -> None:
        await thor_persistence.resume_rehydrated(self, run)

    def set_shadow(self, enabled: bool) -> None:
        """Force shadow mode on / off for every future dispatch.

        The composition root (:class:`~fdai.agents.runtime.PantheonRuntime`)
        calls this to keep the pantheon Thor judge-and-log only, so it
        never double-executes alongside the P1 control loop. Enforce is an
        explicit, separately reviewed promotion - never the default.
        """
        self._shadow_by_default = enabled

    def set_shadow_required(self, predicate: Callable[[], bool]) -> None:
        """Bind a live fail-closed authority predicate for future execution."""
        self._shadow_required = predicate

    def bind_agent_availability(self, probe: Callable[[], Iterable[str]]) -> None:
        """Bind runtime hard-dependency health for Saga/Vidar truthfulness."""
        self._agent_availability = probe

    def _unavailable_dependencies(self) -> frozenset[str]:
        unavailable: set[str] = set()
        if not self._saga_available:
            unavailable.add("Saga")
        if not self._vidar_available:
            unavailable.add("Vidar")
        if self._agent_availability is not None:
            try:
                unavailable.update(str(name) for name in self._agent_availability())
            except Exception:  # noqa: BLE001 - health probe failure must fail closed
                self.record_behavior("dependency_probe:unavailable")
                unavailable.update({"Saga", "Vidar"})
        return frozenset(name for name in unavailable if name in {"Saga", "Vidar"})

    def _approver_unavailable(self) -> bool:
        if self._agent_availability is None:
            return False
        try:
            return "Var" in {str(name) for name in self._agent_availability()}
        except Exception:  # noqa: BLE001 - approval probe failure must not fail open
            self.record_behavior("approver_probe:unavailable")
            return True

    def _must_shadow(self) -> bool:
        if self._shadow_by_default:
            return True
        if self._unavailable_dependencies():
            return True
        try:
            return self._shadow_required()
        except Exception:  # noqa: BLE001 - authority-provider failure must fail closed
            self.record_behavior("authority:unavailable")
            return True

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        self._warm_retry_strategy_cache()

    def _warm_retry_strategy_cache(self) -> None:
        unavailable = self._unavailable_dependencies()
        capabilities = {
            "executor_bound": self._executor is not _default_executor,
            "execution_audit_recorder_bound": self._execution_audit_recorder is not None,
            "execution_audit_required": self._require_execution_audit,
            "execution_resource_lock_bound": self._execution_resource_lock is not None,
            "execution_resource_lock_required": self._require_execution_resource_lock,
            "action_semantics_bound": self._action_semantics is not None,
            "preflight_simulator_bound": self._preflight_simulator is not None,
            "saga_available": "Saga" not in unavailable,
            "vidar_available": "Vidar" not in unavailable,
            "shadow_forced": self._shadow_by_default or bool(unavailable),
            "recorded_at": self._now().isoformat(),
        }
        self._retry_strategy_cache.set("executor_capabilities", capabilities)
        self.record_behavior("retry_strategy_cache:warmed")

    def health(self) -> dict[str, Any]:
        """Expose dispatcher state for Heimdall's probe / runtime health."""
        active = sum(1 for r in self.action_runs.values() if r.state not in _TERMINAL_STATES)
        unavailable = self._unavailable_dependencies()
        shadow_forced = self._shadow_by_default or bool(unavailable)
        terminal = [r for r in self.action_runs.values() if r.state in _TERMINAL_STATES]
        successes = sum(1 for r in terminal if r.state is ActionRunState.SUCCEEDED)
        rollback_triggers = sum(
            1
            for r in self.action_runs.values()
            if r.state
            in {ActionRunState.FAILED, ActionRunState.ROLLED_BACK, ActionRunState.ROLLBACK_FAILED}
        )
        race_failures = self.behavior_snapshot().get("dispatch:lock_contention", 0)
        race_denominator = len(self.action_runs)
        kpis: dict[str, dict[str, object]] = {
            "execution_success_rate": _kpi_ratio(successes, len(terminal), unit="ratio"),
            "rollback_trigger_rate": _kpi_ratio(
                rollback_triggers,
                len(self.action_runs),
                unit="ratio",
            ),
            "race_failure_rate": _kpi_ratio(
                int(race_failures) if isinstance(race_failures, int) else 0,
                race_denominator,
                unit="ratio",
            ),
        }
        return {
            "agent": "Thor",
            "status": "degraded" if shadow_forced else "ok",
            "status_reason": ("hard_dependency_unavailable" if unavailable else "shadow_forced")
            if shadow_forced
            else "ready",
            "active_runs": active,
            "retained_runs": len(self.action_runs),
            "locked_resources": len(self._resource_locks),
            "shadow_forced": shadow_forced,
            "saga_available": "Saga" not in unavailable,
            "vidar_available": "Vidar" not in unavailable,
            "dependency_failure": sorted(unavailable),
            "retry_strategy_cache": self._retry_strategy_cache.get(
                "executor_capabilities",
                {
                    "evidence_state": "not_observed",
                    "executor_bound": False,
                    "action_semantics_bound": self._action_semantics is not None,
                    "preflight_simulator_bound": self._preflight_simulator is not None,
                },
            ),
            "execution_outcomes": {
                "terminal": len(terminal),
                "succeeded": successes,
                "rollback_triggers": rollback_triggers,
                "race_failures": race_failures if isinstance(race_failures, int) else 0,
            },
            "latency_samples": {
                "count": 0,
                "unit": "seconds",
                "evidence_state": "not_observed",
            },
            "kpis": kpis,
            "behavior": self.behavior_snapshot(),
            "preflight": {
                "simulator_bound": self._preflight_simulator is not None,
                "receipt_ttl_seconds": self._preflight_receipt_ttl_seconds,
                "outcome_counts": {
                    key.removeprefix("preflight:"): value
                    for key, value in self.behavior_snapshot().items()
                    if key.startswith("preflight:")
                },
            },
        }

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if payload.get("kind") in {"human_assignment", "handover_knowledge"}:
            self.record_behavior("assignment_non_action_ignored")
            return
        if topic == "object.verdict":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="verdict:rejected_owner",
            ):
                await self._emit_terminal_rejection(
                    payload,
                    outcome="verdict_producer_not_forseti",
                )
                return
            if payload.get("kind") == "document_ingestion":
                self.record_behavior("document_verdict_ignored")
                return
            if payload.get("kind") == "architecture_review":
                self.record_behavior("architecture_review_verdict_ignored")
                return
            if payload.get("kind") == "capacity_graduation":
                self.record_behavior("capacity_graduation_verdict_ignored")
                return
            if is_non_action_verdict(payload):
                await thor_persistence.hold_advisory_correlation(self, payload)
                self.record_behavior("non_action_verdict_ignored")
                return
            await self.dispatch_verdict(payload)
        elif topic == "object.approval":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="approval:rejected_owner",
            ):
                return
            if payload.get("kind") == "test_context_review":
                self.record_behavior("test_context_approval_ignored")
                return
            if payload.get("kind") == "document_ingestion":
                self.record_behavior("document_approval_ignored")
                return
            if payload.get("kind") != "action":
                self.record_behavior("non_action_approval_ignored")
                return
            await self._handle_approval(payload)
        elif topic == "object.rollback":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="rollback:rejected_owner",
            ):
                return
            await self._handle_rollback(payload)
        elif topic == "object.recovery-effect-observation":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="effect_observation:rejected_owner",
            ):
                return
            await self._handle_effect_observation(payload)

    # ---- helpers -------------------------------------------------------

    def _release_lock(self, resource_id: object) -> None:
        thor_persistence.release_lock(self, resource_id)

    def _evict_terminal_overflow(self) -> None:
        thor_persistence.evict_terminal_overflow(self)

    def _find_active_run(self, resource_id: str) -> ActionRun | None:
        return thor_persistence.find_active_run(self, resource_id)

    async def _emit_action_run(self, run: ActionRun) -> None:
        await thor_persistence.emit_action_run(self, run)

    async def _delete_terminal_state(self, run: ActionRun) -> None:
        await thor_persistence.delete_terminal_state(self, run)

    async def _finalize_terminal_replay(self, run: ActionRun) -> None:
        await thor_persistence.finalize_terminal_replay(self, run)

    async def _release_resource_claim(self, run: ActionRun) -> None:
        await thor_persistence.release_resource_claim(self, run)

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        return thor_introspection.evidence_available(self.action_runs)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        return thor_introspection.introspect(
            spec=self.spec,
            runs=self.action_runs,
            shadow_forced=self._shadow_by_default,
            question=question,
            context=context,
        )


async def _default_executor(context: dict[str, Any]) -> bool:
    """Default executor for tests: always succeed. Fork overrides."""
    return True


__all__ = [
    "Thor",
    "ActionRun",
    "ActionRunState",
    "ActionExecutor",
    "ActionRunStore",
    "ExecutionAuditRecorder",
]
