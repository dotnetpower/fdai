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
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from weakref import WeakValueDictionary

from fdai.agents._framework import (
    action_run_lineage,
    action_semantics,
    thor_dispatch_validation,
    thor_execution,
    thor_introspection,
    thor_persistence,
    thor_preflight,
    vidar_dr,
)
from fdai.agents._framework.action_run_identity import (
    approval_matches_action_run,
    bounded_rollback_ref,
    rollback_matches_action_run,
)
from fdai.agents._framework.action_run_lineage import (
    bounded_operational_context as _bounded_operational_context,
)
from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.advisory_verdicts import is_non_action_verdict
from fdai.agents._framework.approval_readback import read_current_action_approval
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
from fdai.agents._framework.thor_action_run import (
    kinetic_proposal as _kinetic_proposal,
)
from fdai.agents._framework.thor_action_run import (
    kinetic_proposal_matches as _kinetic_proposal_matches,
)
from fdai.agents._framework.thor_action_run import (
    prospective_lineage as _prospective_lineage,
)
from fdai.agents._framework.thor_correlation import resolve_correlation_claim
from fdai.agents._framework.thor_development_authority import ThorDevelopmentAuthorityMixin
from fdai.agents._framework.thor_effect_verification import ThorEffectVerificationMixin
from fdai.agents._framework.thor_execution import (
    ExecutionResourceUnavailableError as _ExecutionResourceUnavailableError,
)
from fdai.core.operational_context.test_context_dispatch import (
    TestContextDispatchBinding,
    TestContextDispatchGuard,
)
from fdai.shared.contracts.models import (
    Autonomy,
    FullAuthorityDevelopmentProfile,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

_resolved_autonomy_ceiling = thor_dispatch_validation.resolved_autonomy_ceiling
_selected_action_matches = thor_dispatch_validation.selected_action_matches
_bounded_params = thor_dispatch_validation.bounded_params
_missing_wire_safeguards = thor_dispatch_validation.missing_wire_safeguards
_dry_run_obligation_only = thor_dispatch_validation.dry_run_obligation_only
_ACCEPTED_RISK_VERDICTS = frozenset({"auto", "hil", "deny", "shadow"})

ActionExecutor = Callable[[dict[str, Any]], Awaitable[bool]]
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


class _ReentrantAsyncLock:
    """Serialize a correlation while allowing synchronous bus callbacks in one task."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    async def __aenter__(self) -> None:
        current = asyncio.current_task()
        if current is not None and current is self._owner:
            self._depth += 1
            return
        await self._lock.acquire()
        self._owner = current
        self._depth = 1

    async def __aexit__(self, *_args: object) -> None:
        if asyncio.current_task() is not self._owner:
            raise RuntimeError("correlation lock released by a non-owner task")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


def _positive_quorum(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("quorum MUST be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        parsed = int(value)
    else:
        raise TypeError("quorum MUST be an integer")
    return max(1, parsed)


class Thor(ThorDevelopmentAuthorityMixin, ThorEffectVerificationMixin, Agent):
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

    async def dispatch_verdict(self, verdict: dict[str, Any]) -> ActionRun:
        """Serialize duplicate delivery for one correlation before dispatch."""

        correlation = str(verdict.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            resource_id = str(verdict.get("resource_id") or "")
            if resource_id:
                resource_lock = self._resource_dispatch_locks.setdefault(
                    resource_id,
                    asyncio.Lock(),
                )
                async with resource_lock:
                    run = await self._dispatch_verdict_once(
                        verdict,
                        defer_auto_execution=True,
                    )
            else:
                run = await self._dispatch_verdict_once(
                    verdict,
                    defer_auto_execution=True,
                )
        if run.verdict == "auto" and run.state is ActionRunState.VERDICTED:
            await self._execute(run)
        return run

    async def _dispatch_verdict_once(
        self,
        verdict: dict[str, Any],
        *,
        defer_auto_execution: bool = False,
    ) -> ActionRun:
        correlation = str(verdict.get("correlation_id", ""))
        action_type = str(verdict.get("action_type", ""))
        risk_verdict = str(verdict.get("risk_verdict", "hil"))
        if risk_verdict not in _ACCEPTED_RISK_VERDICTS:
            self.record_behavior("dispatch:invalid_risk_verdict")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="invalid_risk_verdict",
            )
        resolved_autonomy_ceiling = _resolved_autonomy_ceiling(verdict)
        if resolved_autonomy_ceiling is Autonomy.ENFORCE_HIL and risk_verdict == "auto":
            risk_verdict = "hil"
        if risk_verdict == "shadow":
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        resource_id = verdict.get("resource_id")
        raw_decision_case = verdict.get("decision_case")
        decision_case = action_run_lineage.bounded_decision_case(raw_decision_case)
        raw_params = verdict.get("params")
        params = _bounded_params(raw_params)
        if params is None:
            self.record_behavior("dispatch:invalid_params")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="invalid_params",
            )
        operational_context = _bounded_operational_context(verdict.get("operational_context"))
        if verdict.get("operational_context") is not None and operational_context is None:
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        raw_kinetic_proposal = verdict.get("kinetic_proposal")
        kinetic_proposal = _kinetic_proposal(raw_kinetic_proposal)
        raw_prospective_lineage = verdict.get("prospective_lineage")
        prospective_lineage = _prospective_lineage(raw_prospective_lineage)
        semantic_arbitration = verdict.get("reason") in {
            "arbitration_resolved",
            "arbitration_unresolved",
        }
        invalid_decision_case = raw_decision_case is not None and (
            decision_case is None
            or not action_type
            or not _selected_action_matches(decision_case, action_type)
        )
        invalid_kinetic_proposal = raw_kinetic_proposal is not None and (
            kinetic_proposal is None
            or not _kinetic_proposal_matches(
                kinetic_proposal,
                correlation_id=correlation,
                action_type=action_type,
                resource_id=resource_id,
                params=params,
                decision_case=decision_case,
            )
        )
        invalid_prospective_lineage = raw_prospective_lineage is not None and (
            prospective_lineage is None
            or kinetic_proposal is None
            or prospective_lineage.correlation_id != correlation
            or prospective_lineage.proposal_id != kinetic_proposal.proposal_id
            or prospective_lineage.operational_plan_id != kinetic_proposal.operational_plan_id
            or prospective_lineage.mutation_plan_digest != kinetic_proposal.plan.digest
        )
        if (
            (semantic_arbitration and decision_case is None)
            or invalid_decision_case
            or invalid_kinetic_proposal
            or invalid_prospective_lineage
        ):
            risk_verdict = "deny"
            action_type = ""
            kinetic_proposal = None
            prospective_lineage = None
            if invalid_kinetic_proposal:
                self.record_behavior("kinetic_proposal:invalid")
            if invalid_prospective_lineage:
                self.record_behavior("prospective_lineage:invalid")
        elif kinetic_proposal is not None:
            self.record_behavior("kinetic_proposal:validated")

        if risk_verdict in {"auto", "hil"} and not action_type:
            self.record_behavior("dispatch:action_unavailable")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="triage_action_unavailable",
            )

        # Idempotency: at-least-once delivery means the same verdict can arrive
        # twice. Keying the run by correlation is not enough - a re-delivery
        # after the first run terminated (lock released) would start a SECOND
        # run and re-execute. Return the existing run for a correlation we have
        # already dispatched, so a duplicate verdict is a no-op (defense in
        # depth with the event idempotency_key dedup at ingress).
        raw_idempotency_key = verdict.get("idempotency_key")
        if (
            not isinstance(raw_idempotency_key, str) or not raw_idempotency_key.strip()
        ) and verdict.get("producer_principal") is not None:
            self.record_behavior("dispatch:missing_idempotency_key")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="missing_verdict_idempotency_key",
            )
        idempotency_key = (
            raw_idempotency_key.strip()
            if isinstance(raw_idempotency_key, str) and raw_idempotency_key.strip()
            else correlation
        )
        action_idempotency_key = str(verdict.get("action_idempotency_key") or idempotency_key)
        existing_by_corr = self.action_runs.get(correlation)
        if existing_by_corr is not None:
            if existing_by_corr.idempotency_key != action_idempotency_key:
                self.record_behavior("dispatch:correlation_reuse_rejected")
                return await self._emit_terminal_rejection(
                    verdict,
                    outcome="correlation_reuse_rejected",
                    correlation_id=f"{correlation}:rejected:{idempotency_key}",
                    params_extra={"rejected_correlation_id": correlation},
                )
            self.record_behavior("dispatch:duplicate")
            if existing_by_corr.state not in _TERMINAL_STATES:
                await self._resume_rehydrated(existing_by_corr)
            elif not existing_by_corr.terminal_published:
                await self._emit_action_run(existing_by_corr)
                await self._finalize_terminal_replay(existing_by_corr)
            else:
                await self._finalize_terminal_replay(existing_by_corr)
            return existing_by_corr
        existing_by_idempotency = self._idempotency_runs.get(action_idempotency_key)
        if existing_by_idempotency is not None:
            self.record_behavior("dispatch:idempotent_duplicate")
            return existing_by_idempotency

        # Per-resource mutex: refuse to start a new run while another is
        # active on the same resource. Second dispatcher waits for the
        # first to terminate before starting.
        if resource_id and resource_id in self._resource_locks:
            existing = self._find_active_run(str(resource_id))
            if existing is not None:
                self.record_behavior("dispatch:lock_contention")
                return await self._emit_terminal_rejection(
                    verdict,
                    outcome="resource_active_action_run_contention",
                    params_extra={"blocking_correlation_id": existing.correlation_id},
                )
            retained = next(
                (
                    run
                    for run in self.action_runs.values()
                    if run.resource_id == str(resource_id) and run.state in _TERMINAL_STATES
                ),
                None,
            )
            if retained is not None:
                self.record_behavior("dispatch:terminal_fence")
                if retained.terminal_published:
                    await self._finalize_terminal_replay(retained)
                else:
                    await self._emit_action_run(retained)
                    await self._finalize_terminal_replay(retained)
            else:
                raise RuntimeError("resource mutation fence has no recoverable ActionRun")

        # Degrade to shadow when hard dependencies are missing.
        shadow_mode = (
            resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
            or self._must_shadow()
            or not (self._saga_available and self._vidar_available)
        )
        wire_safeguard_required = verdict.get("producer_principal") is not None
        dry_run_evidence = None
        dry_run_receipt = None
        safeguards = verdict.get("safeguards")
        if isinstance(safeguards, Mapping):
            dry_run_evidence = str(safeguards.get("dry_run_evidence") or "").strip() or None
            raw_dry_run = safeguards.get("dry_run_receipt") or verdict.get("dry_run_receipt")
            dry_run_receipt = str(raw_dry_run).strip() if raw_dry_run is not None else None
            if dry_run_receipt and dry_run_evidence is None:
                dry_run_evidence = "upstream_receipt"
        elif verdict.get("dry_run_receipt") is not None:
            dry_run_evidence = "upstream_receipt"
            dry_run_receipt = str(verdict.get("dry_run_receipt")).strip()
        if risk_verdict in {"auto", "hil"} and wire_safeguard_required:
            missing_safeguards = _missing_wire_safeguards(verdict)
            if missing_safeguards:
                self.record_behavior("dispatch:missing_safeguards")
                if not shadow_mode:
                    return await self._emit_terminal_rejection(
                        verdict,
                        outcome="missing_safeguards",
                        params_extra={"missing_safeguards": list(missing_safeguards)},
                    )
            elif not shadow_mode and _dry_run_obligation_only(verdict):
                self.record_behavior("dispatch:dry_run_obligation_only")

        # Propagate the approval quorum the judge set (2 for irreversible
        # actions, agent-pantheon.md 4.6). Floor at 1 so a forged / malformed
        # verdict can never yield a zero-or-negative quorum that would let an
        # action execute with no approver; Thor MUST NOT hard-code 1 and drop
        # the judge's two-approver requirement.
        try:
            required_quorum = (
                action_semantics.quorum_for(action_type, self._action_semantics)
                if self._action_semantics is not None
                or (verdict.get("producer_principal") is not None and "safeguards" in verdict)
                else 1
            )
            original_quorum = _positive_quorum(
                verdict.get(
                    "original_quorum_required",
                    verdict.get("quorum_required", 1),
                )
            )
            if verdict.get("development_authority") is None:
                original_quorum = max(original_quorum, required_quorum)
            effective_quorum = _positive_quorum(
                verdict.get("effective_quorum_required", original_quorum),
            )
            effective_quorum = max(effective_quorum, original_quorum)
        except (TypeError, ValueError):
            self.record_behavior("dispatch:invalid_quorum")
            return await self._emit_terminal_rejection(
                verdict,
                outcome="invalid_quorum",
            )
        if risk_verdict == "auto" and original_quorum >= 2 and not shadow_mode:
            risk_verdict = "hil"
            self.record_behavior("dispatch:auto_quorum_lowered")
        action_id = action_run_lineage.optional_bounded_text(
            verdict.get("action_id"),
            field_name="action_id",
        )
        rollback_contract = (
            action_semantics.rollback_contract_for(action_type, self._action_semantics)
            if self._action_semantics is not None
            else str(verdict.get("rollback_contract", "state_forward_only"))
        )
        authority = self._admit_development_verdict(
            evidence=verdict.get("development_authority"),
            action={
                "action_type": action_type,
                "action_id": action_id,
                "resource_id": resource_id,
                "params": params,
                "idempotency_key": action_idempotency_key,
                "rollback_contract": rollback_contract,
                "initiator_principal": verdict.get("initiator_principal"),
            },
            risk_verdict=risk_verdict,
            original_quorum=original_quorum,
            effective_quorum=effective_quorum,
        )
        risk_verdict = authority.risk_verdict
        effective_quorum = authority.effective_quorum
        run = ActionRun(
            correlation_id=correlation,
            action_type=action_type,
            resource_id=resource_id,
            state=ActionRunState.VERDICTED,
            verdict=risk_verdict,
            action_id=action_id,
            idempotency_key=action_idempotency_key,
            params=params,
            shadow_mode=shadow_mode,
            resolved_autonomy_ceiling=resolved_autonomy_ceiling,
            quorum_required=effective_quorum,
            original_quorum_required=original_quorum,
            effective_quorum_required=effective_quorum,
            development_authority=authority.evidence,
            initiator_principal=verdict.get("initiator_principal"),
            rollback_contract=rollback_contract,
            decision_case=decision_case,
            operational_context=operational_context,
            test_context_guard=(
                TestContextDispatchBinding.model_validate(verdict["test_context_guard"])
                if verdict.get("test_context_guard") is not None
                else None
            ),
            workflow_action=action_run_lineage.bounded_workflow_action(
                verdict.get("workflow_action")
            ),
            kinetic_proposal=(
                kinetic_proposal.model_dump(mode="json") if kinetic_proposal is not None else None
            ),
            prospective_lineage=(
                prospective_lineage.model_dump(mode="json")
                if prospective_lineage is not None
                else None
            ),
            dry_run_evidence=dry_run_evidence,
            dry_run_receipt=dry_run_receipt,
            approval_expires_at=(
                min(
                    self._now() + timedelta(seconds=self._hil_timeout_seconds),
                    authority.grant.valid_until,
                )
                if risk_verdict == "hil" and authority.grant is not None
                else self._now() + timedelta(seconds=self._hil_timeout_seconds)
                if risk_verdict == "hil"
                else None
            ),
        )
        run.preflight_required = wire_safeguard_required and (
            dry_run_evidence == "declared_obligation"
            or thor_preflight.high_risk(run, self._action_semantics)
        )
        claim_status, existing = await resolve_correlation_claim(self._state_store, run)
        if claim_status in {"execution_completed", "correlation_completed"}:
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = (
                "duplicate_execution_already_completed"
                if claim_status == "execution_completed"
                else "duplicate_correlation_already_completed"
            )
            self.action_runs[correlation] = run
            self._idempotency_runs[run.idempotency_key] = run
            await self._emit_action_run(run)
            self.record_behavior("dispatch:completed_duplicate")
            return run
        if claim_status == "contended":
            raise _ExecutionResourceUnavailableError
        if claim_status == "active":
            if existing is None:
                raise RuntimeError("Thor active correlation has no ActionRun")
            self.record_behavior("dispatch:idempotent_duplicate")
            return existing
        self.action_runs[correlation] = run
        self._idempotency_runs[run.idempotency_key] = run
        if resource_id:
            self._resource_locks.add(str(resource_id))
        try:
            if risk_verdict == "auto" and not shadow_mode:
                if not await self._claim_execution_resource(run):
                    run.transition(ActionRunState.DENY_DROPPED)
                    run.outcome = "duplicate_execution_already_completed"
                    await self._emit_action_run(run)
                    self._release_lock(resource_id)
                    return run
            # Emit the initial VERDICTED state so downstream consumers
            # (audit chain, Var) see the lifecycle start.
            await self._emit_action_run(run)
            # Record the verdict split so scenario checks can prove shadow and
            # deny paths never mutate.
            self.record_behavior(f"dispatch:{risk_verdict}")
            if shadow_mode:
                self.record_behavior("dispatch:shadow")
                # Distinguish a policy shadow (forced) from a degraded shadow (a
                # hard dependency - Saga/Vidar - is down), so a scenario can see
                # a safety-relevant degradation, not just "shadow".
                if self._unavailable_dependencies():
                    self.record_behavior("dispatch:degraded")

            if risk_verdict == "deny":
                run.transition(ActionRunState.DENY_DROPPED)
                await self._emit_action_run(run)
                self._release_lock(resource_id)
                return run

            if risk_verdict == "hil":
                if not shadow_mode and self._approver_unavailable():
                    run.outcome = "hil_held_approver_unavailable"
                    run.transition(ActionRunState.DENY_DROPPED)
                    await self._emit_action_run(run)
                    await self._release_resource_claim(run)
                    self._release_lock(resource_id)
                    self.record_behavior("dispatch:hil_approver_unavailable")
                    return run
                run.transition(ActionRunState.HIL_PENDING)
                await self._emit_action_run(run)
                # Lock is held intentionally across the HIL wait; released
                # when _execute (on approval) or the reject path terminates.
                return run

            # auto path (releases the lock via _execute's own finally)
            if defer_auto_execution:
                return run
            await self._execute(run)
            return run
        except Exception:
            # Fail-safe: a lifecycle emit (bus hiccup) MUST NOT leave the
            # resource locked forever - that would deadlock every future
            # action on it (permanent dispatch:lock_contention). Release and
            # re-raise. The HIL path returns normally, so its intentional lock
            # hold is unaffected by this guard.
            self.record_behavior("publication:unavailable")
            if run.state is ActionRunState.VERDICTED and not run.resource_claimed:
                run.outcome = "action_run_publication_unavailable"
            raise

    async def _invoke_executor(self, run: ActionRun) -> bool:
        return await thor_execution.invoke_executor(self, run)

    async def _claim_execution_resource(self, run: ActionRun) -> bool:
        return await thor_execution.claim_execution_resource(self, run)

    async def _emit_terminal_rejection(
        self,
        verdict: Mapping[str, Any],
        *,
        outcome: str,
        correlation_id: str | None = None,
        params_extra: Mapping[str, Any] | None = None,
    ) -> ActionRun:
        run_correlation = correlation_id or str(verdict.get("correlation_id") or "")
        run_idempotency = str(
            verdict.get("action_idempotency_key")
            or verdict.get("idempotency_key")
            or run_correlation
        )
        params = _bounded_params(verdict.get("params")) or {}
        if params_extra:
            params.update(dict(params_extra))
        run = ActionRun(
            correlation_id=run_correlation,
            action_type=str(verdict.get("action_type") or ""),
            resource_id=verdict.get("resource_id"),
            state=ActionRunState.VERDICTED,
            verdict="deny",
            action_id=action_run_lineage.optional_bounded_text(
                verdict.get("action_id"),
                field_name="action_id",
            ),
            idempotency_key=run_idempotency,
            params=params,
            shadow_mode=True,
            resolved_autonomy_ceiling=Autonomy.SHADOW_ONLY,
            outcome=outcome,
            initiator_principal=verdict.get("initiator_principal"),
            rollback_contract=str(verdict.get("rollback_contract", "state_forward_only")),
        )
        if run.correlation_id not in self.action_runs:
            self.action_runs[run.correlation_id] = run
            self._idempotency_runs[run.idempotency_key] = run
        await self._emit_action_run(run)
        run.transition(ActionRunState.DENY_DROPPED)
        await self._emit_action_run(run)
        self._release_lock(run.resource_id)
        return run

    async def _handle_approval(self, approval: dict[str, Any]) -> None:
        correlation = str(approval.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            run_to_execute = await self._handle_approval_locked(approval, correlation=correlation)
        if run_to_execute is not None:
            await self._execute(run_to_execute)

    async def _handle_approval_locked(
        self,
        approval: dict[str, Any],
        *,
        correlation: str,
    ) -> ActionRun | None:
        run = self.action_runs.get(correlation)
        if run is None:
            self.record_behavior("approval:unknown_run")
            return None
        if require_topic_owner(
            self,
            "object.approval",
            approval,
            behavior="approval:rejected_owner",
        ):
            return None
        run_identity = run.to_dict()
        run_identity["action_run_identity"] = run.action_run_identity()
        run_identity["_action_run_identity_verified"] = True
        if not approval_matches_action_run(approval, run_identity):
            self.record_behavior("approval:identity_mismatch")
            raise ValueError("approval identity does not match the current ActionRun")
        self._validate_development_approval(run, approval)
        # Idempotency: only a run still awaiting its HIL decision may act on an
        # approval. At-least-once delivery can redeliver the same object.approval
        # (or a duplicate can arrive), and without this guard an approval for a
        # run already approved / executing / terminal would re-enter _execute -
        # double-executing a completed mutation via the privileged executor, or
        # re-running rollback. dispatch_verdict has its own idempotency guard;
        # this is the matching one for the approval path.
        if run.state != ActionRunState.HIL_PENDING:
            self.record_behavior("approval:duplicate")
            if run.state is ActionRunState.APPROVED:
                return run
            if run.state in _TERMINAL_STATES and not run.terminal_published:
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
            elif run.state in _TERMINAL_STATES:
                await self._finalize_terminal_replay(run)
            return None
        if run.approval_expires_at is None or self._now() >= run.approval_expires_at:
            await self._expire_approval(run)
            return None
        if approval.get("state") == "approved":
            if not run.shadow_mode and self._approval_state_store is not None:
                if self._approver_authorizer is None:
                    run.transition(ActionRunState.REJECTED)
                    run.outcome = "approval_readback_unavailable"
                    await self._emit_action_run(run)
                    self.record_behavior("approval:readback_unavailable")
                    self._release_lock(run.resource_id)
                    return None
                try:
                    await read_current_action_approval(
                        store=self._approval_state_store,
                        action_run=run.to_dict(),
                        can_approve=self._approver_authorizer,
                        clock=self._now,
                        development_profile=self._development_profile,
                        development_executor_principal=self._development_executor_principal,
                        development_binding_source=self._development_binding_source,
                        can_own=self._owner_authorizer,
                    )
                except (PermissionError, ValueError):
                    run.transition(ActionRunState.REJECTED)
                    run.outcome = "approval_readback_rejected"
                    await self._emit_action_run(run)
                    self.record_behavior("approval:readback_rejected")
                    self._release_lock(run.resource_id)
                    return None
            run.transition(ActionRunState.APPROVED)
            if vidar_dr.is_failover_action_type(run.action_type):
                await self._emit_action_run(run)
            return run
        else:
            if not run.resource_claimed and not await self._claim_execution_resource(run):
                run.transition(ActionRunState.DENY_DROPPED)
                run.outcome = "duplicate_execution_already_completed"
                await self._emit_action_run(run)
                self._release_lock(run.resource_id)
                return None
            try:
                run.transition(ActionRunState.REJECTED)
                await self._emit_action_run(run)
                await self._release_resource_claim(run)
            finally:
                self._release_lock(run.resource_id)
        return None

    async def expire_pending_approvals(self) -> int:
        """Expire bounded HIL and effect-verification waits."""

        expired = [
            run
            for run in self.action_runs.values()
            if run.state is ActionRunState.HIL_PENDING
            and (run.approval_expires_at is None or self._now() >= run.approval_expires_at)
        ]
        for run in expired:
            lock = self._correlation_locks.setdefault(
                run.correlation_id,
                _ReentrantAsyncLock(),
            )
            async with lock:
                if run.state is ActionRunState.HIL_PENDING and (
                    run.approval_expires_at is None or self._now() >= run.approval_expires_at
                ):
                    await self._expire_approval(run)
        expired_effects = [
            run
            for run in self.action_runs.values()
            if run.state is ActionRunState.EFFECT_PENDING
            and (
                run.effect_verification_expires_at is None
                or self._now() >= run.effect_verification_expires_at
            )
        ]
        for run in expired_effects:
            lock = self._correlation_locks.setdefault(
                run.correlation_id,
                _ReentrantAsyncLock(),
            )
            async with lock:
                if run.state is ActionRunState.EFFECT_PENDING and (
                    run.effect_verification_expires_at is None
                    or self._now() >= run.effect_verification_expires_at
                ):
                    run.transition(ActionRunState.FAILED)
                    run.outcome = "effect_verification_expired"
                    await self._emit_action_run(run)
                    self.record_behavior("effect_verification:expired")
        expired_dr_contracts = [
            run
            for run in self.action_runs.values()
            if run.state is ActionRunState.APPROVED
            and vidar_dr.is_failover_action_type(run.action_type)
            and run.outcome == "dr_failover_contract_pending"
            and (run.approval_expires_at is None or self._now() >= run.approval_expires_at)
        ]
        for run in expired_dr_contracts:
            lock = self._correlation_locks.setdefault(
                run.correlation_id,
                _ReentrantAsyncLock(),
            )
            async with lock:
                if (
                    run.state is ActionRunState.APPROVED
                    and run.outcome == "dr_failover_contract_pending"
                    and (run.approval_expires_at is None or self._now() >= run.approval_expires_at)
                ):
                    await self._deny_dr_failover_contract(run, "dr_failover_contract_timeout")
                    self.record_behavior("dr_failover_contract:timeout")
        return len(expired) + len(expired_effects) + len(expired_dr_contracts)

    async def _expire_approval(self, run: ActionRun) -> None:
        await asyncio.shield(self._expire_approval_critical(run))

    async def _expire_approval_critical(self, run: ActionRun) -> None:
        if not run.resource_claimed and not await self._claim_execution_resource(run):
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = "duplicate_execution_already_completed"
            await self._emit_action_run(run)
            self._release_lock(run.resource_id)
            return
        try:
            run.transition(ActionRunState.REJECTED)
            run.outcome = "approval_expired"
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self.record_behavior("approval:expired")
        finally:
            self._release_lock(run.resource_id)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise RuntimeError("Thor clock MUST be timezone-aware")
        return now.astimezone(UTC)

    async def _handle_rollback(self, rollback: dict[str, Any]) -> None:
        correlation = str(rollback.get("correlation_id", ""))
        lock = self._correlation_locks.setdefault(correlation, _ReentrantAsyncLock())
        async with lock:
            await self._handle_rollback_locked(rollback, correlation=correlation)

    async def _handle_rollback_locked(
        self,
        rollback: dict[str, Any],
        *,
        correlation: str,
    ) -> None:
        if require_topic_owner(
            self,
            "object.rollback",
            rollback,
            behavior="rollback:rejected_owner",
        ):
            return
        if rollback.get("kind") == vidar_dr.DR_CONTRACT_KIND:
            await self._handle_dr_failover_contract_decision(rollback)
            return
        if rollback.get("kind") == vidar_dr.DR_OUTCOME_KIND:
            self.record_behavior("dr_failover_outcome:observed")
            return
        if rollback.get("kind") == "rollback_rehearsal_receipt":
            self.record_behavior("rollback_rehearsal:observed")
            return
        run = self.action_runs.get(correlation)
        if run is not None:
            run_identity = run.to_dict()
            run_identity["action_run_identity"] = run.action_run_identity()
            run_identity["_action_run_identity_verified"] = True
        if run is not None and not rollback_matches_action_run(rollback, run_identity):
            self.record_behavior("rollback:identity_mismatch")
            return
        rollback_ref = bounded_rollback_ref(rollback.get("rollback_ref"))
        rollback_state = str(rollback.get("state") or "")
        succeeded = rollback_state == "succeeded" and rollback_ref is not None
        if run is not None and run.state is ActionRunState.ROLLBACK_FAILED and succeeded:
            run.rollback_ref = rollback_ref
            run.outcome = "rollback_succeeded"
            run.transition(ActionRunState.ROLLED_BACK)
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self._release_lock(run.resource_id)
            return
        if run is not None and run.state in _TERMINAL_STATES:
            if run.terminal_published:
                await self._finalize_terminal_replay(run)
            else:
                await self._emit_action_run(run)
                await self._finalize_terminal_replay(run)
            return
        if run is None or run.state not in {
            ActionRunState.FAILED,
            ActionRunState.EXECUTION_UNKNOWN,
        }:
            return
        run.rollback_ref = rollback_ref if succeeded else None
        if succeeded:
            run.outcome = "rollback_succeeded"
            next_state = ActionRunState.ROLLED_BACK
        elif rollback_state == "refused":
            run.outcome = "rollback_refused"
            next_state = ActionRunState.ROLLBACK_REFUSED
        else:
            run.outcome = "rollback_failed"
            next_state = ActionRunState.ROLLBACK_FAILED
        run.transition(next_state)
        await self._emit_action_run(run)
        self.record_behavior(run.outcome)
        await self._release_resource_claim(run)
        self._release_lock(run.resource_id)

    async def _handle_dr_failover_contract_decision(self, decision: Mapping[str, Any]) -> None:
        identity = decision.get("action_run_identity")
        if not isinstance(identity, str):
            self.record_behavior("dr_failover_contract:invalid")
            return
        run = self._find_run_by_identity(identity)
        if run is None:
            self._dr_failover_contract_decisions.set(identity, dict(decision))
            self.record_behavior("dr_failover_contract:unknown_run")
            return
        if run.state in _TERMINAL_STATES or run.state in {
            ActionRunState.EXECUTING,
            ActionRunState.EFFECT_PENDING,
        }:
            self.record_behavior("dr_failover_contract:late_ignored")
            return
        if decision.get("decision") == "held" and decision.get("reason") == "approval_required":
            self.record_behavior("dr_failover_contract:awaiting_approval")
            return
        if run.state in {ActionRunState.VERDICTED, ActionRunState.HIL_PENDING}:
            self.record_behavior("dr_failover_contract:awaiting_approval")
            return
        self._dr_failover_contract_decisions.set(identity, dict(decision))
        self.record_behavior(f"dr_failover_contract:{decision.get('decision') or 'unknown'}")
        run.dr_failover_contract_decision = dict(decision)
        if self._state_store is not None:
            await self._state_store.save(run)
        if decision.get("decision") == "held":
            await self._deny_dr_failover_contract(
                run,
                f"dr_failover_contract_held:{vidar_dr.decision_hold_reason(decision)}",
            )
            return
        if (
            run.state is ActionRunState.APPROVED
            and run.outcome == "dr_failover_contract_pending"
            and vidar_dr.decision_allows_executor_io(decision)
        ):
            run.outcome = None
            await self._execute(run)

    async def _wait_for_dr_failover_contract(self, run: ActionRun) -> bool:
        if not vidar_dr.is_failover_action_type(run.action_type) or run.shadow_mode:
            return False
        decision = run.dr_failover_contract_decision or self._dr_failover_contract_decisions.get(
            run.action_run_identity()
        )
        if vidar_dr.decision_allows_executor_io(decision):
            run.dr_failover_contract_decision = dict(decision or {})
            return False
        if (
            decision is not None
            and decision.get("decision") == "held"
            and decision.get("reason") != "approval_required"
        ):
            await self._deny_dr_failover_contract(
                run,
                f"dr_failover_contract_held:{vidar_dr.decision_hold_reason(decision)}",
            )
            return True
        if run.approval_expires_at is not None and self._now() >= run.approval_expires_at:
            await self._deny_dr_failover_contract(run, "dr_failover_contract_timeout")
            self.record_behavior("dr_failover_contract:timeout")
            return True
        if run.state is not ActionRunState.APPROVED:
            run.transition(ActionRunState.APPROVED)
        run.outcome = "dr_failover_contract_pending"
        await self._emit_action_run(run)
        self.record_behavior("dr_failover_contract:waiting")
        return True

    async def _deny_dr_failover_contract(self, run: ActionRun, outcome: str) -> None:
        if run.state in _TERMINAL_STATES:
            return
        run.transition(ActionRunState.DENY_DROPPED)
        run.outcome = outcome
        await self._emit_action_run(run)
        await self._release_resource_claim(run)
        self._release_lock(run.resource_id)

    def _find_run_by_identity(self, identity: str) -> ActionRun | None:
        for run in self.action_runs.values():
            if run.action_run_identity() == identity:
                return run
        return None

    # ---- helpers -------------------------------------------------------

    def _release_lock(self, resource_id: Any) -> None:
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
