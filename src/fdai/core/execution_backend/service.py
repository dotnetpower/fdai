"""Fail-closed orchestration over execution backends and a durable ledger."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.shared.providers.execution_backend import (
    ExecutionAttempt,
    ExecutionAttemptOperation,
    ExecutionBackend,
    ExecutionBackendCapabilities,
    ExecutionBackendError,
    ExecutionBackendHealth,
    ExecutionBackendPlan,
    ExecutionBackendReceipt,
    ExecutionBackendRequest,
    ExecutionCleanupState,
    ExecutionLedgerRecord,
    ExecutionStatus,
    ExecutionSubmissionLedger,
)

from .profiles import ExecutionBackendKind, ExecutionBackendProfileRegistry


class ExecutionBackendCoordinator:
    """Persist lifecycle state without deciding eligibility, approval, or rollback."""

    def __init__(
        self,
        *,
        profiles: ExecutionBackendProfileRegistry,
        backends: Mapping[ExecutionBackendKind, ExecutionBackend],
        ledger: ExecutionSubmissionLedger,
        retention: timedelta = timedelta(days=30),
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if retention <= timedelta(0):
            raise ValueError("execution ledger retention MUST be positive")
        self._profiles = profiles
        self._backends = dict(backends)
        self._ledger = ledger
        self._retention = retention
        self._clock = clock

    async def start(self, request: ExecutionBackendRequest) -> ExecutionBackendReceipt:
        profile = self._profiles.require_enabled(request.profile_id)
        self._validate_request_profile(request, profile)
        backend = self._backend(profile.backend_kind)
        plan = await backend.plan(request, profile=profile)
        now = self._now()
        candidate = ExecutionLedgerRecord(
            idempotency_key=request.idempotency_key,
            workload_id=request.workload_id,
            artifact_digest=request.artifact_digest,
            profile_id=profile.profile_id,
            profile_version=profile.version,
            backend_kind=profile.backend_kind.value,
            owner_trace=request.owner_trace,
            stop_condition=request.stop_condition,
            audit_ref=request.audit_ref,
            scope_ref=request.scope_ref,
            region=request.region,
            status=ExecutionStatus.PLANNED,
            submission_ref=None,
            receipt_ref=None,
            detail="backend plan validated",
            cancel_requested=False,
            cleanup_state=ExecutionCleanupState.PENDING,
            created_at=now,
            updated_at=now,
            retention_until=now + self._retention,
        )
        record = await self._ledger.create(candidate)
        if record != candidate:
            self._validate_duplicate(record, request)
            return _receipt_from_record(record, already_existed=True)
        await self._attempt(record, ExecutionAttemptOperation.SUBMIT)
        try:
            receipt = await backend.submit(plan)
        except Exception as exc:  # noqa: BLE001 - remote acceptance is ambiguous
            record = await self._mark_ambiguous(
                record,
                f"submit result is ambiguous: {type(exc).__name__}",
            )
            raise ExecutionBackendError(record.detail) from exc
        record = await self._apply_receipt(record, receipt)
        return _receipt_from_record(record)

    async def reconcile(self, idempotency_key: str) -> ExecutionBackendReceipt:
        record = await self._require_record(idempotency_key)
        if record.status.terminal:
            return _receipt_from_record(record)
        profile = self._profiles.require(record.profile_id)
        if self._now() - record.created_at >= timedelta(seconds=profile.max_timeout_seconds):
            return await self.cancel(idempotency_key, reason="submission exceeded timeout")
        if record.submission_ref is None:
            record = await self._mark_ambiguous(record, "submission reference was lost")
            return _receipt_from_record(record)
        await self._attempt(record, ExecutionAttemptOperation.STATUS)
        try:
            receipt = await self._backend(profile.backend_kind).status(record.submission_ref)
        except Exception as exc:  # noqa: BLE001 - lost provider status fails closed
            record = await self._mark_ambiguous(
                record,
                f"provider status is unavailable: {type(exc).__name__}",
            )
            return _receipt_from_record(record)
        return _receipt_from_record(await self._apply_receipt(record, receipt))

    async def cancel(
        self,
        idempotency_key: str,
        *,
        reason: str = "cancellation requested",
    ) -> ExecutionBackendReceipt:
        record = await self._require_record(idempotency_key)
        if record.status.terminal:
            return _receipt_from_record(record)
        if record.submission_ref is None:
            record = await self._mark_ambiguous(record, "cannot cancel without submission ref")
            return _receipt_from_record(record)
        submission_ref = record.submission_ref
        record = await self._save(
            record,
            cancel_requested=True,
            detail=reason,
        )
        await self._attempt(record, ExecutionAttemptOperation.CANCEL)
        profile = self._profiles.require(record.profile_id)
        backend = self._backend(profile.backend_kind)
        try:
            receipt = await backend.cancel(submission_ref)
        except Exception:  # noqa: BLE001 - reconcile a possible cancel race
            try:
                receipt = await backend.status(submission_ref)
            except Exception as status_exc:  # noqa: BLE001 - state cannot be proven
                record = await self._mark_ambiguous(
                    record,
                    "cancellation and terminal status could not be confirmed",
                )
                raise ExecutionBackendError(record.detail) from status_exc
        return _receipt_from_record(await self._apply_receipt(record, receipt))

    async def collect_receipt(self, idempotency_key: str) -> ExecutionBackendReceipt:
        record = await self._require_record(idempotency_key)
        if record.submission_ref is None:
            raise ExecutionBackendError("cannot collect receipt without submission ref")
        await self._attempt(record, ExecutionAttemptOperation.COLLECT_RECEIPT)
        profile = self._profiles.require(record.profile_id)
        try:
            receipt = await self._backend(profile.backend_kind).collect_receipt(
                record.submission_ref
            )
        except Exception as exc:  # noqa: BLE001 - receipt evidence is incomplete
            record = await self._mark_ambiguous(
                record,
                f"receipt collection failed: {type(exc).__name__}",
            )
            raise ExecutionBackendError(record.detail) from exc
        return _receipt_from_record(await self._apply_receipt(record, receipt))

    async def cleanup(self, idempotency_key: str) -> ExecutionLedgerRecord:
        record = await self._require_record(idempotency_key)
        if not record.status.terminal or record.submission_ref is None:
            raise ExecutionBackendError("cleanup requires a terminal submission")
        await self._attempt(record, ExecutionAttemptOperation.CLEANUP)
        profile = self._profiles.require(record.profile_id)
        result = await self._backend(profile.backend_kind).cleanup(record.submission_ref)
        return await self._save(
            record,
            cleanup_state=result.state,
            detail=result.detail,
        )

    async def shadow_probe(
        self,
        request: ExecutionBackendRequest,
    ) -> tuple[ExecutionBackendPlan, ExecutionBackendCapabilities, ExecutionBackendHealth]:
        profile = self._profiles.require(request.profile_id)
        self._validate_request_profile(request, profile)
        backend = self._backend(profile.backend_kind)
        capabilities = await backend.capabilities()
        health = await backend.health()
        plan = await backend.plan(request, profile=profile)
        return plan, capabilities, health

    def _validate_request_profile(self, request, profile) -> None:  # type: ignore[no-untyped-def]
        if request.profile_version != profile.version:
            raise ExecutionBackendError("request profile version does not match server profile")
        if request.workload_id not in profile.workload_ids:
            raise ExecutionBackendError("request workload is outside the server profile")
        if request.region not in profile.regions or request.scope_ref not in profile.scope_refs:
            raise ExecutionBackendError("request region or scope is outside the server profile")
        if profile.artifact_digest is not None and (
            request.artifact_digest != profile.artifact_digest
        ):
            raise ExecutionBackendError("request artifact digest does not match server profile")

    def _validate_duplicate(
        self,
        record: ExecutionLedgerRecord,
        request: ExecutionBackendRequest,
    ) -> None:
        if (
            record.workload_id != request.workload_id
            or record.artifact_digest != request.artifact_digest
            or record.profile_id != request.profile_id
            or record.profile_version != request.profile_version
            or record.owner_trace != request.owner_trace
            or record.stop_condition != request.stop_condition
            or record.audit_ref != request.audit_ref
        ):
            raise ExecutionBackendError("idempotency key conflicts with another submission")

    def _backend(self, kind: ExecutionBackendKind) -> ExecutionBackend:
        try:
            return self._backends[kind]
        except KeyError as exc:
            raise ExecutionBackendError(f"execution backend {kind.value!r} is not bound") from exc

    async def _require_record(self, idempotency_key: str) -> ExecutionLedgerRecord:
        record = await self._ledger.get(idempotency_key)
        if record is None:
            raise LookupError(f"unknown execution submission {idempotency_key!r}")
        return record

    async def _attempt(
        self,
        record: ExecutionLedgerRecord,
        operation: ExecutionAttemptOperation,
    ) -> None:
        attempts = await self._ledger.attempts(record.idempotency_key)
        await self._ledger.append_attempt(
            ExecutionAttempt(
                idempotency_key=record.idempotency_key,
                sequence=len(attempts) + 1,
                operation=operation,
                status=record.status,
                detail=record.detail,
                recorded_at=self._now(),
            )
        )

    async def _apply_receipt(
        self,
        record: ExecutionLedgerRecord,
        receipt: ExecutionBackendReceipt,
    ) -> ExecutionLedgerRecord:
        if record.submission_ref is not None and (receipt.submission_ref != record.submission_ref):
            return await self._mark_ambiguous(record, "provider changed submission reference")
        return await self._save(
            record,
            status=receipt.status,
            submission_ref=receipt.submission_ref,
            receipt_ref=receipt.receipt_ref,
            detail=receipt.detail,
        )

    async def _mark_ambiguous(
        self,
        record: ExecutionLedgerRecord,
        detail: str,
    ) -> ExecutionLedgerRecord:
        return await self._save(record, status=ExecutionStatus.AMBIGUOUS, detail=detail)

    async def _save(
        self,
        record: ExecutionLedgerRecord,
        **changes: Any,
    ) -> ExecutionLedgerRecord:
        candidate = replace(record, updated_at=self._now(), **changes)
        return await self._ledger.update(candidate, expected_revision=record.revision)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("execution coordinator clock MUST be timezone-aware")
        return value


def _receipt_from_record(
    record: ExecutionLedgerRecord,
    *,
    already_existed: bool = False,
) -> ExecutionBackendReceipt:
    reference = record.submission_ref or f"ledger:{record.idempotency_key}"
    return ExecutionBackendReceipt(
        status=record.status,
        submission_ref=reference,
        receipt_ref=record.receipt_ref or reference,
        detail=record.detail,
        already_existed=already_existed,
    )


__all__ = ["ExecutionBackendCoordinator"]
