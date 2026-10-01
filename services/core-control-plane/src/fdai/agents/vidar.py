"""Vidar - Recovery (Wave 3 behavior).

Vidar performs rollback per an ActionType's `rollback_contract` and
DR failover. Contract-specific rollback executors are injected by the
composition root; an unbound contract fails closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.pantheon import _VIDAR
from fdai.agents._framework.vidar_dr_runtime import VidarDrRuntimeMixin
from fdai.agents._framework.vidar_observability import VidarObservabilityMixin
from fdai.agents._framework.vidar_rollback_records import (
    _DEFAULT_CLAIM_LEASE,
    _DEFAULT_REHEARSAL_TIMEOUT_SECONDS,
    _MAX_CLAIM_LEASE,
    RollbackExecutor,
    RollbackRecord,
    RollbackRehearsalPort,
    _CachedRollback,
    _RollbackLockEntry,
)
from fdai.agents._framework.vidar_rollback_records import (
    RollbackClaimInProgressError as RollbackClaimInProgressError,
)
from fdai.agents._framework.vidar_rollback_records import (
    _rollback_request_digest as _rollback_request_digest,
)
from fdai.agents._framework.vidar_rollback_records import (
    _rollback_state_key as _rollback_state_key,
)
from fdai.agents._framework.vidar_rollback_runtime import VidarRollbackRuntimeMixin
from fdai.shared.contracts.models import FullAuthorityDevelopmentProfile
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.state_store import StateStore


class Vidar(
    VidarDrRuntimeMixin,
    VidarRollbackRuntimeMixin,
    VidarObservabilityMixin,
    Agent,
):
    """Wave-3 Vidar: rollback executor. Hard dependency for Thor."""

    #: Cap the in-process ledger so a long-running pantheon replica does
    #: not leak. The durable rollback trail is Saga's audit-chain; this
    #: list is only a shadow / observability convenience so callers can
    #: `snapshot()` recent rollback decisions in tests. FIFO eviction on
    #: overflow keeps the tail (most recent) while the durable chain
    #: retains full history.
    _MAX_RECORDS: int = 10_000

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        executors: Mapping[str, RollbackExecutor] | None = None,
        action_executors: Mapping[tuple[str, str], RollbackExecutor] | None = None,
        state_store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
        claim_lease: timedelta = _DEFAULT_CLAIM_LEASE,
        rollback_executor_timeout_seconds: float | None = None,
        rollback_contracts_by_action_type: Mapping[str, str] | None = None,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_executor_principal: str | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
        allow_process_local_rollback: bool = False,
        rollback_rehearsal_port: RollbackRehearsalPort | None = None,
        rollback_rehearsal_cadence: timedelta = timedelta(days=30),
        rollback_rehearsal_timeout_seconds: float = _DEFAULT_REHEARSAL_TIMEOUT_SECONDS,
        max_rehearsals_per_tick: int = 16,
    ) -> None:
        if claim_lease <= timedelta(0) or claim_lease > _MAX_CLAIM_LEASE:
            raise ValueError("claim_lease MUST be greater than zero and at most one hour")
        if rollback_executor_timeout_seconds is not None and rollback_executor_timeout_seconds <= 0:
            raise ValueError("rollback_executor_timeout_seconds MUST be positive")
        if rollback_rehearsal_cadence <= timedelta(0):
            raise ValueError("rollback_rehearsal_cadence MUST be positive")
        if rollback_rehearsal_timeout_seconds <= 0:
            raise ValueError("rollback_rehearsal_timeout_seconds MUST be positive")
        if max_rehearsals_per_tick < 1 or max_rehearsals_per_tick > 128:
            raise ValueError("max_rehearsals_per_tick MUST be between 1 and 128")
        if rollback_contracts_by_action_type is not None and (
            len(rollback_contracts_by_action_type) > self._MAX_RECORDS
            or any(
                not str(action_type).strip()
                or len(str(action_type)) > 256
                or not str(contract).strip()
                or len(str(contract)) > 128
                for action_type, contract in rollback_contracts_by_action_type.items()
            )
        ):
            raise ValueError("rollback contracts must be bounded and non-empty")
        super().__init__(spec=_VIDAR)
        self.bus = bus
        self._executors = dict(executors or {})
        self._action_executors = dict(action_executors or {})
        self._rollback_contracts_by_action_type = dict(rollback_contracts_by_action_type or {})
        self._state_store = state_store
        self._allow_process_local_rollback = allow_process_local_rollback
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._development_profile = development_profile
        self._development_executor_principal = development_executor_principal
        self._development_binding_source = development_binding_source
        self._rollback_rehearsal_port = rollback_rehearsal_port
        self._rollback_rehearsal_cadence = rollback_rehearsal_cadence
        self._rollback_rehearsal_timeout_seconds = rollback_rehearsal_timeout_seconds
        self._max_rehearsals_per_tick = max_rehearsals_per_tick
        self._claim_lease = claim_lease
        self._rollback_executor_timeout_seconds = (
            rollback_executor_timeout_seconds
            if rollback_executor_timeout_seconds is not None
            else min(max(claim_lease.total_seconds() / 2, 1.0), 300.0)
        )
        self._owner_token = uuid4().hex
        self._rollback_locks: dict[tuple[str, str], _RollbackLockEntry] = {}
        self.records: list[RollbackRecord] = []
        # Idempotency guard: at-least-once delivery means the same failed
        # ActionRun can arrive twice. Rolling a resource back twice is not a
        # no-op for a real rollback contract (double PITR restore, double
        # revert), so one immutable ActionRun identity is rolled back at most once. Bounded so
        # the guard cannot leak on a long-lived recovery principal. Publication
        # completion is tracked separately so a broker failure can replay safely.
        self._rollback_results: BoundedLruDict[tuple[str, str], _CachedRollback] = BoundedLruDict(
            self._MAX_RECORDS
        )
        self._published_rollbacks: BoundedLruSet[tuple[str, str]] = BoundedLruSet(self._MAX_RECORDS)
        self._rollback_publication_claims: set[tuple[str, str]] = set()
        self._process_local_terminal_fences: BoundedLruDict[
            tuple[str, str],
            str,
        ] = BoundedLruDict(self._MAX_RECORDS)
        self._rollback_path_validations: BoundedLruDict[str, dict[str, object]] = BoundedLruDict(
            self._MAX_RECORDS
        )
        self._dr_contract_decisions: BoundedLruDict[str, dict[str, object]] = BoundedLruDict(
            self._MAX_RECORDS
        )
        self._dr_outcomes: BoundedLruDict[str, dict[str, object]] = BoundedLruDict(
            self._MAX_RECORDS
        )
        self._rehearsal_receipts: BoundedLruDict[str, dict[str, object]] = BoundedLruDict(
            self._MAX_RECORDS
        )
        self._last_rehearsal_by_action_type: BoundedLruDict[str, datetime] = BoundedLruDict(
            self._MAX_RECORDS
        )
        self._last_dr_readiness: dict[str, object] = {
            "evidence_state": "not_observed",
            "coverage_ratio": None,
            "durable_store_ready": self._state_store is not None,
            "validated_action_types": 0,
            "missing_action_types": 0,
            "unit": "ratio",
        }
        self._durable_publication_pending = 0

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        self._validate_rollback_paths()
        await self._run_rollback_rehearsals()

    def bind_rollback_contracts(self, contracts_by_action_type: Mapping[str, str]) -> None:
        if len(contracts_by_action_type) > self._MAX_RECORDS or any(
            not str(action_type).strip()
            or len(str(action_type)) > 256
            or not str(contract).strip()
            or len(str(contract)) > 128
            for action_type, contract in contracts_by_action_type.items()
        ):
            raise ValueError("rollback contracts must be bounded and non-empty")
        self._rollback_contracts_by_action_type = dict(contracts_by_action_type)

    def _validate_rollback_paths(self) -> None:
        durable_ready = self._state_store is not None or self._allow_process_local_rollback
        validated = 0
        missing = 0
        self._rollback_path_validations = BoundedLruDict(self._MAX_RECORDS)
        for action_type, contract in sorted(self._rollback_contracts_by_action_type.items()):
            executor_bound = self._rollback_executor(action_type, contract) is not None
            ready = executor_bound and durable_ready
            if ready:
                validated += 1
            else:
                missing += 1
            self._rollback_path_validations.set(
                action_type,
                {
                    "action_type": action_type,
                    "rollback_contract": contract,
                    "executor_bound": executor_bound,
                    "durable_store_ready": durable_ready,
                    "ready": ready,
                },
            )
        total = validated + missing
        self._last_dr_readiness = {
            "evidence_state": "measured" if total else "insufficient_sample",
            "coverage_ratio": (validated / total) if total else None,
            "durable_store_ready": durable_ready,
            "validated_action_types": validated,
            "missing_action_types": missing,
            "unit": "ratio",
        }
        if missing:
            self.record_behavior("rollback_path_validation:failed", missing)
        else:
            self.record_behavior("rollback_path_validation:checked")


__all__ = [
    "RollbackClaimInProgressError",
    "RollbackExecutor",
    "RollbackRecord",
    "Vidar",
]
