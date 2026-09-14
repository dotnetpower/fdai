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

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
)
from fdai.agents._framework.pantheon import _VIDAR
from fdai.shared.providers.state_store import StateStore

_ROLLBACK_STATE_PREFIX = "pantheon/vidar/rollback"
_DEFAULT_CLAIM_LEASE = timedelta(minutes=5)
_MAX_CLAIM_LEASE = timedelta(hours=1)
_MAX_ROLLBACK_REF_LENGTH = 2_048
_ROLLBACK_COMMAND_FIELDS = (
    "correlation_id",
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


@dataclass(frozen=True, slots=True)
class RollbackRecord:
    correlation_id: str
    action_type: str
    resource_id: str | None
    contract: str
    state: str  # succeeded | failed | execution_unknown
    notes: str = ""
    rollback_ref: str | None = None


RollbackExecutor = Callable[[dict[str, Any]], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class _CachedRollback:
    request_digest: str
    record: RollbackRecord


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
    ) -> None:
        if claim_lease <= timedelta(0) or claim_lease > _MAX_CLAIM_LEASE:
            raise ValueError("claim_lease MUST be greater than zero and at most one hour")
        super().__init__(spec=_VIDAR)
        self.bus = bus
        self._executors = dict(executors or {})
        self._state_store = state_store
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._claim_lease = claim_lease
        self._owner_token = uuid4().hex
        self._rollback_lock = asyncio.Lock()
        self.records: list[RollbackRecord] = []
        # Idempotency guard: at-least-once delivery means the same failed
        # ActionRun can arrive twice. Rolling a resource back twice is not a
        # no-op for a real rollback contract (double PITR restore, double
        # revert), so a correlation is rolled back at most once. Bounded so
        # the guard cannot leak on a long-lived recovery principal. Publication
        # completion is tracked separately so a broker failure can replay safely.
        self._rollback_results: BoundedLruDict[str, _CachedRollback] = BoundedLruDict(
            self._MAX_RECORDS
        )
        self._published_rollbacks: BoundedLruSet[str] = BoundedLruSet(self._MAX_RECORDS)

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        # Vidar only reacts on failed ActionRuns.
        if topic != "object.action-run":
            return
        if payload.get("state") != "failed":
            return
        await self.rollback(payload)

    async def rollback(self, action_run: dict[str, Any]) -> RollbackRecord | None:
        async with self._rollback_lock:
            return await self._rollback_locked(action_run)

    async def _rollback_locked(self, action_run: dict[str, Any]) -> RollbackRecord | None:
        correlation_id = str(action_run.get("correlation_id", ""))
        contract = str(action_run.get("rollback_contract", "state_forward_only"))
        request_digest = _rollback_request_digest(action_run, contract=contract)
        if correlation_id:
            existing = self._rollback_results.get(correlation_id)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise ValueError("rollback correlation collides with different action identity")
                if not await self._publish_rollback_once(existing.record):
                    return None
                return existing.record
            if self._state_store is not None:
                return await self._rollback_durable(
                    action_run,
                    correlation_id,
                    contract=contract,
                    request_digest=request_digest,
                )
        rec = await self._execute_rollback(action_run, correlation_id)
        self._remember_rollback(rec, request_digest=request_digest)
        await self._publish_rollback_once(rec)
        return rec

    async def _rollback_durable(
        self,
        action_run: dict[str, Any],
        correlation_id: str,
        *,
        contract: str,
        request_digest: str,
    ) -> RollbackRecord | None:
        store = self._state_store
        if store is None:
            raise RuntimeError("durable rollback requires a StateStore")
        state_key = _rollback_state_key(correlation_id, "state")
        stored = await store.read_state(state_key)
        if stored is None:
            claimed_at = _clock_now(self._clock)
            lease_expires_at = claimed_at + self._claim_lease
            claim = {
                "schema_version": "1.0.0",
                "revision": 1,
                "status": "in_progress",
                "correlation_id": correlation_id,
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
                rec = await self._execute_rollback(action_run, correlation_id)
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
            request_digest=request_digest,
        )
        if stored.get("status") == "terminal":
            rec = _rollback_record_from_state(stored)
        elif stored.get("status") == "in_progress":
            claim_owner_token, lease_expires_at = _rollback_claim_lease(stored)
            if _clock_now(self._clock) < lease_expires_at:
                raise RollbackClaimInProgressError(
                    f"rollback claim remains active until {lease_expires_at.isoformat()}"
                )
            rec = RollbackRecord(
                correlation_id=correlation_id,
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
            request_digest=request_digest,
        )
        return _rollback_record_from_state(stored)

    async def _execute_rollback(
        self,
        action_run: dict[str, Any],
        correlation_id: str,
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
                returned_ref = await executor(_rollback_command(action_run, contract=contract))
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
            existing = self._rollback_results.get(rec.correlation_id)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise ValueError("rollback correlation collides with different action identity")
                return
            self._rollback_results.set(
                rec.correlation_id,
                _CachedRollback(request_digest=request_digest, record=rec),
            )
        self.records.append(rec)
        # FIFO cap - drop the oldest 25% in one shot to amortise the cost.
        if len(self.records) > self._MAX_RECORDS:
            keep_from = len(self.records) - (self._MAX_RECORDS * 3 // 4)
            del self.records[:keep_from]

    async def _publish_rollback_once(self, rec: RollbackRecord) -> bool:
        if rec.correlation_id and await self._rollback_was_published(rec.correlation_id):
            return False
        published = await self._publish_rollback(rec)
        if not published:
            return False
        if rec.correlation_id:
            await self._mark_rollback_published(rec)
        return True

    async def _rollback_was_published(self, correlation_id: str) -> bool:
        if correlation_id in self._published_rollbacks:
            return True
        if self._state_store is None:
            return False
        stored = await self._state_store.read_state(
            _rollback_state_key(correlation_id, "published")
        )
        if stored is None:
            return False
        if stored.get("correlation_id") != correlation_id:
            raise RuntimeError("rollback publication receipt has conflicting identity")
        self._published_rollbacks.add(correlation_id)
        return True

    async def _mark_rollback_published(self, rec: RollbackRecord) -> None:
        receipt = {
            "correlation_id": rec.correlation_id,
            "idempotency_key": f"{rec.correlation_id}:rollback:{rec.state}",
            "state": rec.state,
        }
        if self._state_store is not None:
            key = _rollback_state_key(rec.correlation_id, "published")
            created = await self._state_store.write_state_if_absent(key, receipt)
            if not created:
                stored = await self._state_store.read_state(key)
                if stored != receipt:
                    raise RuntimeError("rollback publication receipt collision")
        self._published_rollbacks.add(rec.correlation_id)

    async def _publish_rollback(self, rec: RollbackRecord) -> bool:
        if self.bus is None:
            return False
        await self.bus.publish(
            "Vidar",
            "object.rollback",
            {
                "producer_principal": "Vidar",
                "correlation_id": rec.correlation_id,
                "idempotency_key": (f"{rec.correlation_id}:rollback:{rec.state}"),
                "action_type": rec.action_type,
                "resource_id": rec.resource_id,
                "contract": rec.contract,
                "state": rec.state,
                "rollback_ref": rec.rollback_ref,
            },
        )
        return True

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Recovery answers rest on rollbacks performed; none is a real gap."""
        return bool(self.records)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        recs = self.records
        facts = {
            **capability_facts(self.spec),
            "rollbacks_recorded": len(recs),
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


def _rollback_state_key(correlation_id: str, suffix: str) -> str:
    digest = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()
    return f"{_ROLLBACK_STATE_PREFIX}/{digest}/{suffix}"


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


def _validate_rollback_state_identity(
    stored: Mapping[str, Any],
    *,
    correlation_id: str,
    request_digest: str,
) -> None:
    if (
        stored.get("correlation_id") != correlation_id
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
