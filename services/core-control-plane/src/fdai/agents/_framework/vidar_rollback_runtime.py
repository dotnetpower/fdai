# mypy: disable-error-code="attr-defined,arg-type,no-any-return,misc"
"""Rollback execution, durable claims, and publication mixin for Vidar."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.agents._framework.action_run_identity import validate_action_run_identity
from fdai.agents._framework.development_authority import admit_development_authority
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.vidar_rollback_records import (
    _ROLLBACK_STATE_PREFIX,
    RollbackExecutor,
    RollbackRecord,
    _CachedRollback,
    _clock_now,
    _execution_unknown_rollback_record,
    _normalize_rollback_ref,
    _parse_rollback_timestamp,
    _resource_id,
    _rollback_claim_lease,
    _rollback_command,
    _rollback_idempotency_key,
    _rollback_publication_receipt_matches,
    _rollback_record_from_state,
    _rollback_record_state,
    _rollback_request_digest,
    _rollback_state_key,
    _RollbackLockEntry,
    _validate_rollback_state_identity,
)


class VidarRollbackRuntimeMixin:
    """Execute rollback commands while preserving Vidar's recovery boundary."""

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
        action_type = str(action_run.get("action_type") or "")
        executor = self._rollback_executor(action_type, contract)
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

    def _rollback_executor(self, action_type: str, contract: str) -> RollbackExecutor | None:
        action_executor = self._action_executors.get((action_type, contract))
        if action_executor is not None:
            return action_executor
        if self._action_executors and action_type in self._rollback_contracts_by_action_type:
            return None
        return self._executors.get(contract)

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
        now = _clock_now(self._clock)
        receipt = self._rollback_publication_receipt(rec, status="publishing", now=now)
        if self._state_store is not None:
            key = _rollback_state_key(
                rec.correlation_id,
                "published",
                rec.action_run_identity,
            )
            created = await self._state_store.write_state_if_absent(key, receipt)
            if not created:
                stored = await self._state_store.read_state(key)
                if _rollback_publication_receipt_matches(
                    stored,
                    rec,
                    status="published",
                ):
                    self._published_rollbacks.add(cache_key)
                    return False
                if _rollback_publication_receipt_matches(stored, rec, status="publishing"):
                    owner = str(stored.get("owner_token") or "") if stored is not None else ""
                    lease_expires_at = (
                        _parse_rollback_timestamp(stored.get("lease_expires_at"))
                        if stored is not None
                        else None
                    )
                    if (
                        owner != self._owner_token
                        and lease_expires_at is not None
                        and now < lease_expires_at
                    ):
                        self.record_behavior("rollback_publication:claim_live")
                        return False
                    expected_revision = int(stored.get("revision", 0)) if stored is not None else 0
                    takeover_receipt = {
                        **receipt,
                        "revision": expected_revision + 1,
                        "previous_owner_token": owner,
                    }
                    if await self._state_store.compare_and_set_state(
                        key,
                        takeover_receipt,
                        expected_revision=expected_revision,
                    ):
                        self.record_behavior("rollback_publication:claim_reclaimed")
                    else:
                        self.record_behavior("rollback_publication:claim_raced")
                        return False
                else:
                    raise RuntimeError("rollback publication receipt collision")
        self._rollback_publication_claims.add(cache_key)
        return True

    async def recover_rollbacks(self) -> int:
        """Publish terminal rollback records that completed before a bus was available."""
        if self._state_store is None:
            return 0
        await self._rehydrate_rehearsal_receipts()
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
            try:
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
            except Exception:  # noqa: BLE001 - one corrupt row must not block recovery
                self.record_behavior("rollback_recovery:row_failed")
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
        receipt = self._rollback_publication_receipt(
            rec,
            status="published",
            now=_clock_now(self._clock),
        )
        if self._state_store is not None:
            key = _rollback_state_key(
                rec.correlation_id,
                "published",
                rec.action_run_identity,
            )
            created = await self._state_store.write_state_if_absent(key, receipt)
            if not created:
                stored = await self._state_store.read_state(key)
                if _rollback_publication_receipt_matches(stored, rec, status="publishing"):
                    owner = str(stored.get("owner_token") or "") if stored is not None else ""
                    if owner != self._owner_token:
                        raise RuntimeError("rollback publication receipt collision")
                    expected_revision = int(stored.get("revision", 0)) if stored is not None else 0
                    await self._state_store.write_state(
                        key,
                        {
                            **dict(stored or {}),
                            **receipt,
                            "revision": expected_revision + 1,
                            "published_at": _clock_now(self._clock).isoformat(),
                        },
                    )
                elif not _rollback_publication_receipt_matches(
                    stored,
                    rec,
                    status="published",
                ):
                    raise RuntimeError("rollback publication receipt collision")
        self._published_rollbacks.add((rec.correlation_id, rec.action_run_identity))

    def _rollback_publication_receipt(
        self,
        rec: RollbackRecord,
        *,
        status: str,
        now: datetime,
    ) -> dict[str, object]:
        receipt: dict[str, object] = {
            "schema_version": "1.0.0",
            "revision": 1,
            "correlation_id": rec.correlation_id,
            "action_run_identity": rec.action_run_identity,
            "idempotency_key": _rollback_idempotency_key(rec),
            "state": rec.state,
            "status": status,
            "owner_token": self._owner_token,
        }
        if status == "publishing":
            receipt["claimed_at"] = now.isoformat()
            receipt["lease_expires_at"] = (now + self._claim_lease).isoformat()
        return receipt

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


__all__ = ["VidarRollbackRuntimeMixin"]
