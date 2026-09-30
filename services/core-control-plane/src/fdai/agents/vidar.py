"""Vidar - Recovery (Wave 3 behavior).

Vidar performs rollback per an ActionType's `rollback_contract` and
DR failover. Contract-specific rollback executors are injected by the
composition root; an unbound contract fails closed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fdai.agents._framework.action_run_identity import (
    is_action_run_identity,
    validate_action_run_identity,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.development_authority import admit_development_authority
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
)
from fdai.agents._framework.pantheon import _VIDAR
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.shared.contracts.models import (
    FullAuthorityDevelopmentProfile,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.state_store import StateStore

_ROLLBACK_STATE_PREFIX = "pantheon/vidar/rollback"
_DEFAULT_CLAIM_LEASE = timedelta(minutes=5)
_MAX_CLAIM_LEASE = timedelta(hours=1)
_MAX_ROLLBACK_REF_LENGTH = 2_048
_ROLLBACK_COMMAND_FIELDS = (
    "correlation_id",
    "action_run_identity",
    "idempotency_key",
    "action_idempotency_key",
    "action_id",
    "action_type",
    "resource_id",
    "state",
    "shadow_mode",
    "resolved_autonomy_ceiling",
    "outcome",
    "operational_success",
    "effect_verification_status",
    "verdict",
    "params",
    "quorum_required",
    "original_quorum_required",
    "effective_quorum_required",
    "development_authority",
    "initiator_principal",
    "rollback_contract",
    "rollback_ref",
    "decision_case",
    "operational_context",
    "workflow_action",
    "kinetic_proposal",
    "prospective_lineage",
    "execution_audit_receipt",
    "approval_expires_at",
)


def _kpi_ratio(numerator: int, denominator: int, *, unit: str = "ratio") -> dict[str, object]:
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


@dataclass(frozen=True, slots=True)
class RollbackRecord:
    correlation_id: str
    action_run_identity: str
    action_type: str
    resource_id: str | None
    contract: str
    state: str  # succeeded | failed | refused | execution_unknown
    notes: str = ""
    rollback_ref: str | None = None


RollbackExecutor = Callable[[dict[str, Any]], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class _CachedRollback:
    request_digest: str
    record: RollbackRecord


@dataclass(slots=True)
class _RollbackLockEntry:
    lock: asyncio.Lock
    users: int = 0


class RollbackClaimInProgressError(RuntimeError):
    """Raised so transport retry or DLQ retains a still-leased rollback."""


class Vidar(Agent):
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
        state_store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
        claim_lease: timedelta = _DEFAULT_CLAIM_LEASE,
        rollback_executor_timeout_seconds: float | None = None,
        rollback_contracts_by_action_type: Mapping[str, str] | None = None,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_executor_principal: str | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
        allow_process_local_rollback: bool = False,
    ) -> None:
        if claim_lease <= timedelta(0) or claim_lease > _MAX_CLAIM_LEASE:
            raise ValueError("claim_lease MUST be greater than zero and at most one hour")
        if rollback_executor_timeout_seconds is not None and rollback_executor_timeout_seconds <= 0:
            raise ValueError("rollback_executor_timeout_seconds MUST be positive")
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
        self._rollback_contracts_by_action_type = dict(rollback_contracts_by_action_type or {})
        self._state_store = state_store
        self._allow_process_local_rollback = allow_process_local_rollback
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._development_profile = development_profile
        self._development_executor_principal = development_executor_principal
        self._development_binding_source = development_binding_source
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
            executor_bound = contract in self._executors
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

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        # Vidar reacts on failed and ambiguous ActionRuns.
        if topic != "object.action-run":
            self.record_behavior("typed_message:ignored")
            return
        if require_topic_owner(
            self,
            topic,
            payload,
            behavior="rollback:rejected_owner",
        ):
            return
        if payload.get("state") not in {"failed", "execution_unknown"}:
            self.record_behavior("action_run:ignored")
            return
        try:
            await self.rollback(payload)
        except ValueError:
            self.record_behavior("rollback:action_identity_mismatch")

    async def rollback(self, action_run: dict[str, Any]) -> RollbackRecord | None:
        if require_topic_owner(
            self,
            "object.action-run",
            action_run,
            behavior="rollback:rejected_owner",
        ):
            return None
        correlation_id = str(action_run.get("correlation_id", ""))
        action_run_identity = validate_action_run_identity(action_run)
        lock_key = (correlation_id, action_run_identity)
        entry = self._rollback_locks.get(lock_key)
        if entry is None:
            entry = _RollbackLockEntry(asyncio.Lock())
            self._rollback_locks[lock_key] = entry
        entry.users += 1
        try:
            async with entry.lock:
                return await self._rollback_locked(action_run)
        finally:
            entry.users -= 1
            if entry.users == 0 and not entry.lock.locked():
                self._rollback_locks.pop(lock_key, None)

    async def _rollback_locked(self, action_run: dict[str, Any]) -> RollbackRecord | None:
        admit_development_authority(
            profile=self._development_profile,
            binding_source=self._development_binding_source,
            evidence=action_run.get("development_authority"),
            action=action_run,
            executor_principal=self._development_executor_principal,
            original_quorum=int(
                action_run.get(
                    "original_quorum_required",
                    action_run.get("quorum_required", 1),
                )
            ),
            now=_clock_now(self._clock),
        )
        correlation_id = str(action_run.get("correlation_id", ""))
        contract = str(action_run.get("rollback_contract", "state_forward_only"))
        action_run_identity = validate_action_run_identity(action_run)
        if correlation_id:
            cache_key = (correlation_id, action_run_identity)
            existing = self._rollback_results.get(cache_key)
            if existing is not None:
                if not await self._publish_rollback_once(existing.record):
                    return None
                return existing.record
            terminal_digest = self._process_local_terminal_fences.get(cache_key)
            if terminal_digest is not None:
                self.record_behavior("rollback:duplicate_terminal")
                return None
            request_digest = _rollback_request_digest(action_run, contract=contract)
            if self._state_store is not None:
                return await self._rollback_durable(
                    action_run,
                    correlation_id,
                    contract=contract,
                    action_run_identity=action_run_identity,
                    request_digest=request_digest,
                )
            if not self._allow_process_local_rollback:
                rec = self._process_local_refusal_record(
                    action_run,
                    correlation_id,
                    contract=contract,
                    action_run_identity=action_run_identity,
                )
                self.record_behavior("rollback:durability_unavailable")
                self._remember_rollback(rec, request_digest=request_digest)
                await self._publish_rollback_once(rec)
                return rec
        else:
            request_digest = _rollback_request_digest(action_run, contract=contract)
        rec = await self._execute_rollback(
            action_run,
            correlation_id,
            action_run_identity=action_run_identity,
        )
        self._remember_rollback(rec, request_digest=request_digest)
        await self._publish_rollback_once(rec)
        return rec

    def _process_local_refusal_record(
        self,
        action_run: Mapping[str, Any],
        correlation_id: str,
        *,
        contract: str,
        action_run_identity: str,
    ) -> RollbackRecord:
        return RollbackRecord(
            correlation_id=correlation_id,
            action_run_identity=action_run_identity,
            action_type=str(action_run.get("action_type", "")),
            resource_id=_resource_id(action_run),
            contract=contract,
            state="refused",
            notes="rollback refused because durable StateStore is unavailable",
        )

    async def _rollback_durable(
        self,
        action_run: dict[str, Any],
        correlation_id: str,
        *,
        contract: str,
        action_run_identity: str,
        request_digest: str,
    ) -> RollbackRecord | None:
        store = self._state_store
        if store is None:
            raise RuntimeError("durable rollback requires a StateStore")
        state_key = _rollback_state_key(correlation_id, "state", action_run_identity)
        stored = await store.read_state(state_key)
        if stored is None:
            claimed_at = _clock_now(self._clock)
            lease_expires_at = claimed_at + self._claim_lease
            claim = {
                "schema_version": "1.0.0",
                "revision": 1,
                "status": "in_progress",
                "correlation_id": correlation_id,
                "action_run_identity": action_run_identity,
                "request_digest": request_digest,
                "owner_token": self._owner_token,
                "claimed_at": claimed_at.isoformat(),
                "lease_expires_at": lease_expires_at.isoformat(),
                "action_type": str(action_run.get("action_type", "")),
                "resource_id": _resource_id(action_run),
                "contract": contract,
            }
            claimed = await store.write_state_with_audit_if_absent(
                state_key,
                claim,
                {
                    "actor": "Vidar",
                    "action_kind": "rollback.claimed",
                    "correlation_id": correlation_id,
                    "request_digest": request_digest,
                    "lease_expires_at": lease_expires_at.isoformat(),
                    "recorded_at": claimed_at.isoformat(),
                },
            )
            if claimed:
                try:
                    rec = await self._execute_rollback(
                        action_run,
                        correlation_id,
                        action_run_identity=action_run_identity,
                    )
                except asyncio.CancelledError:
                    rec = _execution_unknown_rollback_record(
                        action_run,
                        correlation_id,
                        contract=contract,
                        action_run_identity=action_run_identity,
                        notes="rollback execution cancelled before terminal receipt",
                    )
                    rec = await asyncio.shield(
                        self._complete_durable_rollback(
                            state_key=state_key,
                            request_digest=request_digest,
                            rec=rec,
                            claim_owner_token=self._owner_token,
                            lease_expires_at=lease_expires_at,
                        )
                    )
                    self._remember_rollback(rec, request_digest=request_digest)
                    await asyncio.shield(self._publish_rollback_once(rec))
                    raise
                rec = await self._complete_durable_rollback(
                    state_key=state_key,
                    request_digest=request_digest,
                    rec=rec,
                    claim_owner_token=self._owner_token,
                    lease_expires_at=lease_expires_at,
                )
                self._remember_rollback(rec, request_digest=request_digest)
                await self._publish_rollback_once(rec)
                return rec
            stored = await store.read_state(state_key)
            if stored is None:
                raise RuntimeError("rollback claim disappeared after atomic collision")

        _validate_rollback_state_identity(
            stored,
            correlation_id=correlation_id,
            action_run_identity=action_run_identity,
            request_digest=request_digest,
        )
        if stored.get("status") == "terminal":
            rec = _rollback_record_from_state(stored)
        elif stored.get("status") == "in_progress":
            claim_owner_token, lease_expires_at = _rollback_claim_lease(stored)
            if _clock_now(self._clock) < lease_expires_at:
                self.record_behavior("rollback:claim_in_progress")
                self._remember_rollback_hold(
                    RollbackRecord(
                        correlation_id=correlation_id,
                        action_run_identity=str(stored.get("action_run_identity") or ""),
                        action_type=str(stored.get("action_type") or ""),
                        resource_id=(
                            str(stored["resource_id"])
                            if stored.get("resource_id") is not None
                            else None
                        ),
                        contract=str(stored.get("contract") or ""),
                        state="execution_unknown",
                        notes="rollback held by an active durable claim",
                    )
                )
                return None
            rec = RollbackRecord(
                correlation_id=correlation_id,
                action_run_identity=str(stored.get("action_run_identity") or ""),
                action_type=str(stored.get("action_type") or ""),
                resource_id=(
                    str(stored["resource_id"]) if stored.get("resource_id") is not None else None
                ),
                contract=str(stored.get("contract") or ""),
                state="execution_unknown",
                notes="prior rollback claim has no terminal receipt",
            )
            rec = await self._complete_durable_rollback(
                state_key=state_key,
                request_digest=request_digest,
                rec=rec,
                claim_owner_token=claim_owner_token,
                lease_expires_at=lease_expires_at,
            )
        else:
            raise RuntimeError("stored rollback state has an unsupported status")
        self._remember_rollback(rec, request_digest=request_digest)
        await self._publish_rollback_once(rec)
        return rec

    async def _complete_durable_rollback(
        self,
        *,
        state_key: str,
        request_digest: str,
        rec: RollbackRecord,
        claim_owner_token: str,
        lease_expires_at: datetime,
    ) -> RollbackRecord:
        store = self._state_store
        if store is None:
            raise RuntimeError("durable rollback completion requires a StateStore")
        terminal = _rollback_record_state(
            rec,
            request_digest=request_digest,
            claim_owner_token=claim_owner_token,
            lease_expires_at=lease_expires_at,
            completed_by_owner_token=self._owner_token,
        )
        completed = await store.compare_and_set_state_with_audit(
            state_key,
            terminal,
            expected_revision=1,
            audit_entry={
                "actor": "Vidar",
                "action_kind": "rollback.completed",
                "correlation_id": rec.correlation_id,
                "request_digest": request_digest,
                "state": rec.state,
                "rollback_ref": rec.rollback_ref,
                "recorded_at": _clock_now(self._clock).isoformat(),
            },
        )
        if completed:
            return rec
        stored = await store.read_state(state_key)
        if stored is None:
            raise RuntimeError("rollback terminal state disappeared after collision")
        _validate_rollback_state_identity(
            stored,
            correlation_id=rec.correlation_id,
            action_run_identity=rec.action_run_identity,
            request_digest=request_digest,
        )
        return _rollback_record_from_state(stored)

    async def _execute_rollback(
        self,
        action_run: dict[str, Any],
        correlation_id: str,
        *,
        action_run_identity: str,
    ) -> RollbackRecord:
        contract = str(action_run.get("rollback_contract", "state_forward_only"))
        executor = self._executors.get(contract)
        state = "failed"
        notes = f"no rollback executor registered for contract {contract}"
        rollback_ref: str | None = None
        if not correlation_id:
            notes = "rollback refused because correlation_id is empty"
        elif executor is not None:
            try:
                async with asyncio.timeout(self._rollback_executor_timeout_seconds):
                    returned_ref = await executor(_rollback_command(action_run, contract=contract))
            except TimeoutError:
                state = "execution_unknown"
                notes = "rollback executor timed out before terminal receipt"
            except Exception as exc:  # noqa: BLE001 - provider boundary; fail closed
                notes = f"rollback executor raised {type(exc).__name__}"
            else:
                rollback_ref = _normalize_rollback_ref(returned_ref)
                if rollback_ref is not None:
                    state = "succeeded"
                    notes = "rollback executor completed"
                else:
                    notes = "rollback executor returned no receipt"
        rec = RollbackRecord(
            correlation_id=correlation_id,
            action_run_identity=str(action_run_identity),
            action_type=str(action_run.get("action_type", "")),
            resource_id=_resource_id(action_run),
            contract=contract,
            state=state,
            notes=notes,
            rollback_ref=rollback_ref,
        )
        return rec

    def _remember_rollback(
        self,
        rec: RollbackRecord,
        *,
        request_digest: str,
    ) -> None:
        if rec.correlation_id:
            cache_key = (rec.correlation_id, rec.action_run_identity)
            existing = self._rollback_results.get(cache_key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise ValueError("rollback correlation collides with different action identity")
                return
            self._rollback_results.set(
                cache_key,
                _CachedRollback(request_digest=request_digest, record=rec),
            )
            self._process_local_terminal_fences.set(cache_key, request_digest)
        self.record_behavior(f"rollback:{rec.state}")
        self.records.append(rec)
        # FIFO cap - drop the oldest 25% in one shot to amortise the cost.
        if len(self.records) > self._MAX_RECORDS:
            keep_from = len(self.records) - (self._MAX_RECORDS * 3 // 4)
            del self.records[:keep_from]

    def _remember_rollback_hold(self, rec: RollbackRecord) -> None:
        self.records.append(rec)
        if len(self.records) > self._MAX_RECORDS:
            keep_from = len(self.records) - (self._MAX_RECORDS * 3 // 4)
            del self.records[:keep_from]

    async def _publish_rollback_once(self, rec: RollbackRecord) -> bool:
        if self.bus is None:
            return await self._publish_rollback(rec)
        if rec.correlation_id and not await self._claim_rollback_publication(rec):
            self.record_behavior("rollback:duplicate_publication")
            return False
        try:
            published = await self._publish_rollback(rec)
        except BaseException:
            if rec.correlation_id:
                self._rollback_publication_claims.discard(
                    (rec.correlation_id, rec.action_run_identity)
                )
            raise
        if not published:
            if rec.correlation_id:
                self._rollback_publication_claims.discard(
                    (rec.correlation_id, rec.action_run_identity)
                )
            return False
        if rec.correlation_id:
            await self._mark_rollback_published(rec)
            self._published_rollbacks.add((rec.correlation_id, rec.action_run_identity))
            self._rollback_publication_claims.discard((rec.correlation_id, rec.action_run_identity))
        return True

    async def _claim_rollback_publication(self, rec: RollbackRecord) -> bool:
        cache_key = (rec.correlation_id, rec.action_run_identity)
        if cache_key in self._published_rollbacks or cache_key in self._rollback_publication_claims:
            return False
        receipt = {
            "correlation_id": rec.correlation_id,
            "action_run_identity": rec.action_run_identity,
            "idempotency_key": _rollback_idempotency_key(rec),
            "state": rec.state,
            "status": "publishing",
            "owner_token": self._owner_token,
        }
        if self._state_store is not None:
            key = _rollback_state_key(
                rec.correlation_id,
                "published",
                rec.action_run_identity,
            )
            created = await self._state_store.write_state_if_absent(key, receipt)
            if not created:
                stored = await self._state_store.read_state(key)
                published_receipt = {**receipt, "status": "published"}
                if stored == published_receipt:
                    self._published_rollbacks.add(cache_key)
                    return False
                if stored != receipt:
                    raise RuntimeError("rollback publication receipt collision")
        self._rollback_publication_claims.add(cache_key)
        return True

    async def recover_rollbacks(self) -> int:
        """Publish terminal rollback records that completed before a bus was available."""
        if self._state_store is None:
            return 0
        rows, total = await self._state_store.read_state_page(
            _ROLLBACK_STATE_PREFIX,
            limit=self._MAX_RECORDS,
            field="status",
            value="terminal",
        )
        if total > self._MAX_RECORDS:
            raise RuntimeError("Vidar rollback recovery count exceeds its bound")
        recovered = 0
        pending = 0
        for row in rows:
            rec = _rollback_record_from_state(row)
            if await self._rollback_was_published(rec.correlation_id, rec.action_run_identity):
                continue
            pending += 1
            self._remember_rollback(
                rec,
                request_digest=str(row.get("request_digest") or ""),
            )
            if await self._publish_rollback_once(rec):
                recovered += 1
        self._durable_publication_pending = pending - recovered
        return recovered

    async def _rollback_was_published(
        self,
        correlation_id: str,
        action_run_identity: str,
    ) -> bool:
        cache_key = (correlation_id, action_run_identity)
        if cache_key in self._published_rollbacks:
            return True
        if self._state_store is None:
            return False
        stored = await self._state_store.read_state(
            _rollback_state_key(correlation_id, "published", action_run_identity)
        )
        if stored is None:
            return False
        if (
            stored.get("correlation_id") != correlation_id
            or stored.get("action_run_identity") != action_run_identity
        ):
            raise RuntimeError("rollback publication receipt has conflicting identity")
        if stored.get("status") != "published":
            return False
        self._published_rollbacks.add(cache_key)
        return True

    async def _mark_rollback_published(self, rec: RollbackRecord) -> None:
        receipt = {
            "correlation_id": rec.correlation_id,
            "action_run_identity": rec.action_run_identity,
            "idempotency_key": _rollback_idempotency_key(rec),
            "state": rec.state,
            "status": "published",
            "owner_token": self._owner_token,
        }
        if self._state_store is not None:
            key = _rollback_state_key(
                rec.correlation_id,
                "published",
                rec.action_run_identity,
            )
            created = await self._state_store.write_state_if_absent(key, receipt)
            if not created:
                stored = await self._state_store.read_state(key)
                publishing_receipt = {**receipt, "status": "publishing"}
                if stored == publishing_receipt:
                    await self._state_store.write_state(key, receipt)
                elif stored != receipt:
                    raise RuntimeError("rollback publication receipt collision")
        self._published_rollbacks.add((rec.correlation_id, rec.action_run_identity))

    async def _publish_rollback(self, rec: RollbackRecord) -> bool:
        if self.bus is None:
            self.record_behavior("publication:unavailable")
            return False
        await self.bus.publish(
            "Vidar",
            "object.rollback",
            {
                "producer_principal": "Vidar",
                "correlation_id": rec.correlation_id,
                "idempotency_key": _rollback_idempotency_key(rec),
                "action_run_identity": rec.action_run_identity,
                "action_type": rec.action_type,
                "resource_id": rec.resource_id,
                "contract": rec.contract,
                "state": rec.state,
                "rollback_ref": rec.rollback_ref,
            },
        )
        return True

    def health(self) -> dict[str, Any]:
        durability = "durable" if self._state_store is not None else "process_local"
        local_publication_pending = sum(
            1
            for rec in self.records
            if rec.correlation_id
            and (rec.correlation_id, rec.action_run_identity) not in self._published_rollbacks
        )
        terminal_records = [
            rec for rec in self.records if rec.state in {"succeeded", "failed", "execution_unknown"}
        ]
        succeeded = sum(1 for rec in terminal_records if rec.state == "succeeded")
        validation_failures = sum(
            1
            for rec in terminal_records
            if rec.state == "failed" and "validation" in rec.notes.lower()
        )
        readiness_validated = self._last_dr_readiness.get("validated_action_types", 0)
        readiness_missing = self._last_dr_readiness.get("missing_action_types", 0)
        if not isinstance(readiness_validated, int):
            readiness_validated = 0
        if not isinstance(readiness_missing, int):
            readiness_missing = 0
        if readiness_validated + readiness_missing:
            path_failure_numerator = readiness_missing
            path_failure_denominator = readiness_validated + readiness_missing
        else:
            path_failure_numerator = validation_failures
            path_failure_denominator = len(terminal_records)
        durable_ready = self._state_store is not None or self._allow_process_local_rollback
        executor_ready = bool(self._executors)
        status = "ok" if durable_ready and executor_ready else "degraded"
        return {
            "agent": self.spec.name,
            "status": status,
            "status_reason": "ready" if status == "ok" else "rollback_dependency_incomplete",
            "rollback_durability": durability,
            "process_local_rollback_allowed": self._allow_process_local_rollback,
            "rollback_executor_bound": executor_ready,
            "rollback_publication_pending": max(
                local_publication_pending,
                self._durable_publication_pending,
            ),
            "rollback_path_validation": {
                "evidence_state": self._last_dr_readiness["evidence_state"],
                "paths": dict(self._rollback_path_validations.items()),
            },
            "dr_readiness_score": dict(self._last_dr_readiness),
            "rollback_outcomes": {
                "attempts": len(terminal_records),
                "succeeded": succeeded,
                "failed": sum(1 for rec in terminal_records if rec.state == "failed"),
                "refused": sum(1 for rec in terminal_records if rec.state == "refused"),
                "execution_unknown": sum(
                    1 for rec in terminal_records if rec.state == "execution_unknown"
                ),
                "validation_failures": validation_failures,
            },
            "mttr_samples": {
                "count": 0,
                "unit": "seconds",
                "evidence_state": "not_observed",
            },
            "kpis": {
                "rollback_success_rate": _kpi_ratio(succeeded, len(terminal_records)),
                "rollback_path_validation_failure_rate": _kpi_ratio(
                    path_failure_numerator,
                    path_failure_denominator,
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Recovery answers rest on rollbacks performed; none is a real gap."""
        return bool(self.records)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        recs = self.records
        facts = {
            **capability_facts(self.spec),
            "rollbacks_recorded": len(recs),
            "last_correlation_id": None,
            "last_action_type": None,
            "last_state": None,
            "last_contract": None,
            "last_rollback_ref": None,
        }
        if recs:
            last = recs[-1]
            facts.update(
                {
                    "last_correlation_id": last.correlation_id,
                    "last_action_type": last.action_type,
                    "last_state": last.state,
                    "last_contract": last.contract,
                    # The proof the rollback ran, not just that it was
                    # attempted. None when the contract produced no artifact.
                    "last_rollback_ref": last.rollback_ref,
                }
            )
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 파이프라인 Rollback 및 재해 복구 principal인 Vidar입니다. Thor에게 "
                "보고합니다. 실패한 ActionRun을 받아 테스트된 복구 계약으로 Rollback을 조정하고 "
                "증적을 기록합니다. 저는 hard dependency이므로 사용할 수 없으면 새 변경은 "
                "안전하게 중단돼야 합니다. 원래 작업을 판단하거나 승인하거나 실행하지 않습니다. "
                "이 대화 포트는 읽기 전용이며 복구 요청은 운영자 권한으로 타입이 지정된 "
                "파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 프롬프트는 공개하지 않습니다."
            )
            if recs:
                answer += (
                    f" 이 런타임은 Rollback {len(recs)}건을 기록했으며 마지막 기록은 "
                    f"{last.action_type}의 {last.state} 상태와 {last.contract} 계약입니다."
                )
            else:
                answer += " 이 런타임에서 수행한 Rollback은 없습니다."
            answer += f" 근거: {evidence_ref}."
        else:
            answer = (
                "I am Vidar, the pipeline Rollback and disaster-recovery principal. I report to "
                "Thor. I receive failed ActionRuns, coordinate their tested recovery contracts, "
                "and record the evidence. I am a hard dependency, so new changes must stop safely "
                "when I am unavailable. I do not judge, approve, or execute the original action. "
                "This conversational port is read-only; recovery requests re-enter the typed "
                "pipeline under the operator's authority. I do not reveal hidden system prompts."
            )
            if recs:
                rollback_label = "Rollback" if len(recs) == 1 else "Rollbacks"
                answer += (
                    f" This runtime records {len(recs)} {rollback_label}; the latest is "
                    f"{last.action_type} in {last.state} through {last.contract}."
                )
            else:
                answer += " No Rollback has been performed in this runtime."
            answer += f" Evidence: {evidence_ref}."
        return IntrospectionResult(answer=answer, facts=facts)


def _resource_id(action_run: Mapping[str, Any]) -> str | None:
    value = action_run.get("resource_id")
    return value if isinstance(value, str) and value else None


def _rollback_idempotency_key(rec: RollbackRecord) -> str:
    return f"{rec.correlation_id}:{rec.action_run_identity[7:19]}:rollback:{rec.state}"


def _rollback_state_key(
    correlation_id: str,
    suffix: str,
    action_run_identity: str,
) -> str:
    digest = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()
    identity_scope = action_run_identity.removeprefix("sha256:")
    return f"{_ROLLBACK_STATE_PREFIX}/{digest}/{identity_scope}/{suffix}"


def _rollback_request_digest(action_run: Mapping[str, Any], *, contract: str) -> str:
    encoded = json.dumps(
        _rollback_command(action_run, contract=contract),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _rollback_command(
    action_run: Mapping[str, Any],
    *,
    contract: str,
) -> dict[str, Any]:
    command = {
        field: deepcopy(action_run[field])
        for field in _ROLLBACK_COMMAND_FIELDS
        if field in action_run
    }
    if action_run.get("development_authority") is None:
        for field in (
            "original_quorum_required",
            "effective_quorum_required",
            "development_authority",
        ):
            command.pop(field, None)
    command["rollback_contract"] = contract
    return command


def _rollback_record_state(
    rec: RollbackRecord,
    *,
    request_digest: str,
    claim_owner_token: str,
    lease_expires_at: datetime,
    completed_by_owner_token: str,
) -> dict[str, Any]:
    if not _is_sha256_digest(request_digest):
        raise ValueError("rollback request_digest MUST be a sha256 digest")
    if not _is_owner_token(claim_owner_token) or not _is_owner_token(completed_by_owner_token):
        raise ValueError("rollback terminal owner token is malformed")
    if lease_expires_at.tzinfo is None or lease_expires_at.utcoffset() is None:
        raise ValueError("rollback terminal lease expiry MUST include timezone")
    if (
        not rec.correlation_id
        or len(rec.correlation_id) > 512
        or not rec.action_type
        or len(rec.action_type) > 256
        or not rec.contract
        or len(rec.contract) > 128
        or rec.resource_id is not None
        and (not rec.resource_id or len(rec.resource_id) > 2_048)
        or rec.state not in {"succeeded", "failed", "execution_unknown"}
        or len(rec.notes) > 1_024
        or (
            rec.state == "succeeded"
            and (
                rec.rollback_ref is None
                or _normalize_rollback_ref(rec.rollback_ref) != rec.rollback_ref
            )
        )
        or (rec.state != "succeeded" and rec.rollback_ref is not None)
    ):
        raise ValueError("rollback terminal record fields are malformed")
    return {
        "schema_version": "1.0.0",
        "revision": 2,
        "status": "terminal",
        "correlation_id": rec.correlation_id,
        "action_run_identity": rec.action_run_identity,
        "request_digest": request_digest,
        "claim_owner_token": claim_owner_token,
        "lease_expires_at": lease_expires_at.isoformat(),
        "completed_by_owner_token": completed_by_owner_token,
        "action_type": rec.action_type,
        "resource_id": rec.resource_id,
        "contract": rec.contract,
        "state": rec.state,
        "notes": rec.notes,
        "rollback_ref": rec.rollback_ref,
    }


def _execution_unknown_rollback_record(
    action_run: Mapping[str, Any],
    correlation_id: str,
    *,
    contract: str,
    action_run_identity: str,
    notes: str,
) -> RollbackRecord:
    return RollbackRecord(
        correlation_id=correlation_id,
        action_run_identity=action_run_identity,
        action_type=str(action_run.get("action_type", "")),
        resource_id=_resource_id(action_run),
        contract=contract,
        state="execution_unknown",
        notes=notes,
    )


def _validate_rollback_state_identity(
    stored: Mapping[str, Any],
    *,
    correlation_id: str,
    action_run_identity: str,
    request_digest: str,
) -> None:
    if (
        stored.get("correlation_id") != correlation_id
        or stored.get("action_run_identity") != action_run_identity
        or stored.get("request_digest") != request_digest
    ):
        raise ValueError("rollback correlation collides with different action identity")


def _rollback_claim_lease(stored: Mapping[str, Any]) -> tuple[str, datetime]:
    owner_token = stored.get("owner_token")
    lease_expires_at = stored.get("lease_expires_at")
    if (
        stored.get("schema_version") != "1.0.0"
        or stored.get("revision") != 1
        or stored.get("status") != "in_progress"
        or not _is_owner_token(owner_token)
        or not isinstance(lease_expires_at, str)
    ):
        raise RuntimeError("stored rollback claim is malformed")
    return str(owner_token), _parse_lease_expiry(lease_expires_at)


def _clock_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("Vidar clock MUST return a timezone-aware datetime")
    return value.astimezone(UTC)


def _is_owner_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_sha256_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _normalize_rollback_ref(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_ROLLBACK_REF_LENGTH:
        return None
    return normalized


def _parse_lease_expiry(value: str) -> datetime:
    try:
        parsed_expiry = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError("stored rollback state has invalid lease expiry") from exc
    if parsed_expiry.tzinfo is None or parsed_expiry.utcoffset() is None:
        raise RuntimeError("stored rollback state lease expiry MUST include timezone")
    return parsed_expiry.astimezone(UTC)


def _rollback_record_from_state(stored: Mapping[str, Any]) -> RollbackRecord:
    correlation_id = stored.get("correlation_id")
    action_run_identity = stored.get("action_run_identity")
    action_type = stored.get("action_type")
    contract = stored.get("contract")
    notes = stored.get("notes")
    request_digest = stored.get("request_digest")
    claim_owner_token = stored.get("claim_owner_token")
    completed_by_owner_token = stored.get("completed_by_owner_token")
    lease_expires_at = stored.get("lease_expires_at")
    if (
        stored.get("schema_version") != "1.0.0"
        or stored.get("revision") != 2
        or stored.get("status") != "terminal"
        or not isinstance(correlation_id, str)
        or not is_action_run_identity(action_run_identity)
        or not isinstance(action_type, str)
        or not isinstance(contract, str)
        or not isinstance(notes, str)
        or not _is_sha256_digest(request_digest)
        or not _is_owner_token(claim_owner_token)
        or not _is_owner_token(completed_by_owner_token)
        or not isinstance(lease_expires_at, str)
    ):
        raise RuntimeError("stored rollback terminal record is malformed")
    resource_id = stored.get("resource_id")
    rollback_ref = stored.get("rollback_ref")
    rec = RollbackRecord(
        correlation_id=correlation_id,
        action_run_identity=str(action_run_identity),
        action_type=action_type,
        resource_id=resource_id if isinstance(resource_id, str) else None,
        contract=contract,
        state=str(stored["state"]),
        notes=notes,
        rollback_ref=rollback_ref if isinstance(rollback_ref, str) else None,
    )
    try:
        canonical = _rollback_record_state(
            rec,
            request_digest=str(request_digest),
            claim_owner_token=str(claim_owner_token),
            lease_expires_at=_parse_lease_expiry(lease_expires_at),
            completed_by_owner_token=str(completed_by_owner_token),
        )
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError("stored rollback terminal record is malformed") from exc
    if dict(stored) != canonical:
        raise RuntimeError("stored rollback terminal record is malformed")
    return rec


__all__ = [
    "RollbackClaimInProgressError",
    "RollbackExecutor",
    "RollbackRecord",
    "Vidar",
]
