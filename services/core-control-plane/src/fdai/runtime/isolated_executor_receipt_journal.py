"""Durable bound-command inbox; dispatch receipts never resolve quarantine.

An immutable attempt claim precedes publication. Uncertain publication is never
retried here. A bounded CAS index retains work across restart and receipt-before-
closure races; capacity or storage failures prevent new publication.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai_service_contracts.ontology_query import content_digest
from psycopg import InterfaceError, OperationalError
from pydantic import BaseModel, ConfigDict, Field

from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.shared.contracts.models import (
    ExecutorEffectReceipt,
    ExecutorShadowReceipt,
    SafeguardBoundExecutorCommand,
)
from fdai.shared.providers.executor_receipt_journal import (
    BoundExecutorCommandContext,
    ExecutorReceipt,
    ExecutorReceiptRegistrationNotOwnedError,
    ExecutorReceiptRegistrationUnobservedError,
    ExecutorReceiptStorageUnavailableError,
    receipt_matches_command,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "runtime:isolated-executor:"
_INDEX_KEY = f"{_PREFIX}receipt-work"
_CAS_ATTEMPTS = 4
_MAX_RECEIPT_CLOCK_SKEW = timedelta(seconds=30)
_LOGGER = logging.getLogger(__name__)


class BoundCommandCorrelation(BaseModel):
    """Exact command, Core attempt, and target generation with no new authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: SafeguardBoundExecutorCommand
    registration_id: UUID
    reservation_identity_digest: str
    evidence_identity_digest: str
    target_digest: str
    target_fence_generation: int = Field(ge=1)

    @property
    def closure_key(self) -> str:
        """Locate Core's stable attempt closure without manufacturing evidence."""

        return content_digest(
            {
                "domain": "post-release-closure-key",
                "reservation_identity_digest": self.reservation_identity_digest,
                "reservation_attempt": self.command.attempt,
            }
        )


class _ReceiptWork(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(default=0, ge=0)
    commands: tuple[UUID, ...] = ()


class BoundExecutorReceiptJournal:
    """Persist correlation and exact terminal delivery using Core's StateStore.

    Completed rows and attempt claims are retained for replay/conflict detection.
    Pending work is bounded rather than evicted; missing Core closure therefore
    backpressures new dispatch instead of silently losing reconciliation work.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        capacity: int,
        closure_store: PostReleaseClosureStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind durable Core storage, closure reads, and the outstanding-work limit."""

        self._store = store
        self._capacity = capacity
        self._closure_store = closure_store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def register(
        self,
        command: SafeguardBoundExecutorCommand,
        context: BoundExecutorCommandContext,
        *,
        registration_id: UUID,
    ) -> tuple[SafeguardBoundExecutorCommand, bool]:
        """Claim one exact attempt before publication; duplicates never send again.

        A crash after claiming but before sending remains explicitly uncertain.
        No replay can re-run an expired pre-publication guard under a new lock.
        """

        correlation = BoundCommandCorrelation(
            command=command,
            registration_id=registration_id,
            reservation_identity_digest=context.reservation_identity_digest,
            evidence_identity_digest=context.evidence_identity_digest,
            target_digest=context.target_digest,
            target_fence_generation=context.target_fence_generation,
        )
        if (
            str(command.action_id) != context.action_id
            or command.attempt != context.reservation_attempt
            or command.source_revision != context.source_revision
            or command.execution_path.value != context.execution_path
            or command.safeguard_proof_bundle_digest != context.safeguard_bundle_digest
        ):
            raise ValueError("isolated Executor reservation binding mismatched")
        attempt_key = f"{_PREFIX}attempt:{correlation.closure_key}"
        value = correlation.model_dump(mode="json")
        created = await self._store.write_state_with_audit_if_absent(
            attempt_key,
            value,
            self._audit(command.command_id, "command_claimed", registration_id=registration_id),
        )
        if not created:
            prior = BoundCommandCorrelation.model_validate(
                await self._store.read_state(attempt_key)
            )
            if prior.model_dump(
                exclude={
                    "registration_id": True,
                    "command": {"command_id", "issued_at", "deadline_at"},
                }
            ) != correlation.model_dump(
                exclude={
                    "registration_id": True,
                    "command": {"command_id", "issued_at", "deadline_at"},
                }
            ):
                raise ValueError("isolated Executor command attempt binding conflicted")
            return prior.command, False
        await self._store.write_state_with_audit_if_absent(
            self._command_key(command.command_id),
            value,
            self._audit(command.command_id, "command_correlated", registration_id=registration_id),
        )
        await self._change_work(command.command_id, add=True)
        return command, True

    async def accept(self, receipt: ExecutorReceipt, *, partition_key: str) -> bool:
        """Retain exact terminal bytes before the consumer advances its offset.

        Return false for legacy/foreign commands; mismatches and conflicting
        terminal deliveries are durably rejected without replacing the first.
        """

        try:
            return await self._accept(receipt, partition_key=partition_key)
        except (InterfaceError, OperationalError) as exc:
            raise ExecutorReceiptStorageUnavailableError(
                "isolated Executor receipt store unavailable"
            ) from exc

    async def _accept(self, receipt: ExecutorReceipt, *, partition_key: str) -> bool:
        raw = await self._store.read_state(self._command_key(receipt.command_id))
        if raw is None:
            return False
        correlation = BoundCommandCorrelation.model_validate(raw)
        if not _bound_receipt_matches(correlation.command, receipt, partition_key=partition_key):
            await self._reject(receipt, "receipt_binding_mismatch")
            return True
        if await self._store.read_state(self._not_published_key(receipt.command_id)) is not None:
            await self._reject(receipt, "receipt_after_no_publication")
            return True
        key = self._receipt_key(receipt.command_id)
        payload = receipt.model_dump(mode="json")
        created = await self._store.write_state_with_audit_if_absent(
            key, payload, self._audit(receipt.command_id, "terminal_receipt_retained")
        )
        if not created:
            prior = await self._store.read_state(key)
            if prior != payload:
                await self._reject(receipt, "terminal_receipt_conflict")
                return True
        # A late receipt can arrive after its bounded wait was retired. Re-add
        # it so reconciliation remains restart-safe without republishing.
        await self._change_work(receipt.command_id, add=True, touch=True)
        return True

    async def record_not_published(
        self, command: SafeguardBoundExecutorCommand, *, registration_id: UUID
    ) -> None:
        """Persist local no-publication knowledge, then retire work without freeing the claim."""

        try:
            await self._record_not_published(command, registration_id=registration_id)
        except (InterfaceError, OperationalError) as exc:
            raise ExecutorReceiptStorageUnavailableError(
                "isolated Executor receipt store unavailable"
            ) from exc

    async def _record_not_published(
        self, command: SafeguardBoundExecutorCommand, *, registration_id: UUID
    ) -> None:
        raw = await self._store.read_state(self._command_key(command.command_id))
        if raw is None:
            raise ExecutorReceiptRegistrationUnobservedError(
                "isolated Executor registration readback is unavailable"
            )
        correlation = BoundCommandCorrelation.model_validate(raw)
        if correlation.command != command or correlation.registration_id != registration_id:
            raise ExecutorReceiptRegistrationNotOwnedError(
                "isolated Executor no-publication registration mismatched"
            )
        key = self._not_published_key(command.command_id)
        marker = self._not_published_record(correlation)
        await self._store.write_state_with_audit_if_absent(
            key,
            marker,
            self._audit(
                command.command_id, "publication_not_started", registration_id=registration_id
            ),
        )
        if await self._store.read_state(key) != marker:
            raise ValueError("isolated Executor no-publication readback mismatched")
        await self._change_work(command.command_id, add=False)

    async def reconcile(self) -> int:
        """Join terminal receipts to exact persisted Core closures, without I/O dispatch.

        Also finish interrupted work removal from durable no-publication markers.
        Schema 1.1 has no sink-status authority/trust anchor, irrevocable
        non-acceptance proof, or lock-release attestation. Preserve quarantine;
        record the missing evidence rather than calling the closure resolver
        with fabricated PostReleaseReconciliationEvidence.
        """

        try:
            return await self._reconcile()
        except (InterfaceError, OperationalError) as exc:
            raise ExecutorReceiptStorageUnavailableError(
                "isolated Executor receipt store unavailable"
            ) from exc

    async def _reconcile(self) -> int:
        work = await self._read_work()
        completed = 0
        for command_id in work.commands:
            try:
                completed += await self._reconcile_command(command_id)
            except ValueError:
                _LOGGER.error(
                    "isolated_executor_receipt_reconciliation_invalid",
                    extra={"command_id": str(command_id)},
                )
        return completed

    async def _reconcile_command(self, command_id: UUID) -> int:
        observed_work = await self._read_work()
        if command_id not in observed_work.commands:
            return 0
        raw_correlation = await self._store.read_state(self._command_key(command_id))
        if raw_correlation is None:
            raise ValueError("isolated Executor command correlation is unavailable")
        correlation = BoundCommandCorrelation.model_validate(raw_correlation)
        if correlation.command.command_id != command_id:
            raise ValueError("isolated Executor command correlation id mismatched")
        not_published = await self._store.read_state(self._not_published_key(command_id))
        if not_published is not None:
            if not_published != self._not_published_record(correlation):
                raise ValueError("isolated Executor no-publication record mismatched")
            await self._change_work(command_id, add=False)
            return 1
        raw_receipt = await self._store.read_state(self._receipt_key(command_id))
        if raw_receipt is None:
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("isolated Executor receipt journal clock is not timezone-aware")
            if now < correlation.command.deadline_at + _MAX_RECEIPT_CLOCK_SKEW:
                return 0
            timeout_record = {
                "command_id": str(command_id),
                "deadline_at": correlation.command.deadline_at.isoformat(),
                "outcome": "receipt_not_observed_before_deadline",
                "execution_authority": False,
                "effect_verified": False,
            }
            await self._store.write_state_with_audit_if_absent(
                self._receipt_timeout_key(command_id),
                timeout_record,
                self._audit(command_id, "receipt_not_observed_before_deadline"),
            )
            retired = await self._change_work(
                command_id, add=False, expected_revision=observed_work.revision
            )
            return int(retired)
        closure = await self._closure_store.read(correlation.closure_key)
        if closure is None:
            return 0
        identity = closure.identity
        if (
            identity.reservation_identity_digest != correlation.reservation_identity_digest
            or identity.reservation_attempt != correlation.command.attempt
            or identity.evidence_identity_digest != correlation.evidence_identity_digest
            or identity.target_digest != correlation.target_digest
            or identity.target_fence_generation != correlation.target_fence_generation
        ):
            raise ValueError("isolated Executor closure binding mismatched")
        receipt = (
            ExecutorShadowReceipt.model_validate(raw_receipt)
            if raw_receipt.get("schema_version") == "1.0.0"
            else ExecutorEffectReceipt.model_validate(raw_receipt)
        )
        if not _bound_receipt_matches(
            correlation.command, receipt, partition_key=correlation.command.partition_key
        ):
            raise ValueError("isolated Executor durable receipt binding mismatched")
        result = {
            "command_id": str(command_id),
            "safeguard_bundle_digest": correlation.command.safeguard_proof_bundle_digest,
            "receipt_digest": content_digest(dict(raw_receipt)),
            "closure_key": correlation.closure_key,
            "closure_record_digest": closure.record_digest,
            "closure_outcome": closure.outcome.value,
            "outcome": "authoritative_reconciliation_evidence_required",
            "execution_authority": False,
            "effect_verified": False,
        }
        await self._store.write_state_with_audit_if_absent(
            f"{_PREFIX}receipt-reconciliation:{command_id}",
            result,
            self._audit(command_id, "authoritative_reconciliation_evidence_required"),
        )
        await self._change_work(command_id, add=False)
        return 1

    async def _reject(self, receipt: ExecutorReceipt, reason: str) -> None:
        payload = receipt.model_dump(mode="json")
        await self._store.write_state_with_audit_if_absent(
            f"{_PREFIX}receipt-rejected:{receipt.command_id}:{content_digest(payload)}",
            {"reason": reason, "receipt": payload},
            self._audit(receipt.command_id, reason),
        )

    async def _read_work(self) -> _ReceiptWork:
        raw = await self._store.read_state(_INDEX_KEY)
        return _ReceiptWork() if raw is None else _ReceiptWork.model_validate(raw)

    async def _change_work(
        self,
        command_id: UUID,
        *,
        add: bool,
        touch: bool = False,
        expected_revision: int | None = None,
    ) -> bool:
        """Touch intake revisions so an older absence observation cannot retire new work."""

        for _ in range(_CAS_ATTEMPTS):
            prior = await self._read_work()
            if expected_revision is not None and prior.revision != expected_revision:
                return False
            present = command_id in prior.commands
            if present == add and not touch:
                return True
            if add and not present and len(prior.commands) >= self._capacity:
                raise ExecutorReceiptStorageUnavailableError(
                    "isolated Executor durable receipt capacity exceeded"
                )
            commands = (
                (prior.commands if present else (*prior.commands, command_id))
                if add
                else tuple(item for item in prior.commands if item != command_id)
            )
            value = _ReceiptWork(revision=prior.revision + 1, commands=commands)
            audit = self._audit(command_id, "receipt_work_added" if add else "receipt_work_done")
            if prior.revision == 0:
                written = await self._store.write_state_with_audit_if_absent(
                    _INDEX_KEY, value.model_dump(mode="json"), audit
                )
            else:
                written = await self._store.compare_and_set_state_with_audit(
                    _INDEX_KEY,
                    value.model_dump(mode="json"),
                    expected_revision=prior.revision,
                    audit_entry=audit,
                )
            if written:
                return True
            if expected_revision is not None:
                return False
        raise ExecutorReceiptStorageUnavailableError(
            "isolated Executor receipt work contention exceeded"
        )

    @staticmethod
    def _command_key(command_id: UUID) -> str:
        return f"{_PREFIX}command:{command_id}"

    @staticmethod
    def _receipt_key(command_id: UUID) -> str:
        return f"{_PREFIX}terminal-receipt:{command_id}"

    @staticmethod
    def _receipt_timeout_key(command_id: UUID) -> str:
        return f"{_PREFIX}receipt-timeout:{command_id}"

    @staticmethod
    def _not_published_key(command_id: UUID) -> str:
        return f"{_PREFIX}not-published:{command_id}"

    @staticmethod
    def _not_published_record(correlation: BoundCommandCorrelation) -> dict[str, str | bool]:
        command = correlation.command
        return {
            "command_id": str(command.command_id),
            "registration_id": str(correlation.registration_id),
            "action_payload_digest": command.action_payload_digest,
            "safeguard_bundle_digest": command.safeguard_proof_bundle_digest,
            "outcome": "publication_not_started",
            "execution_authority": False,
            "effect_verified": False,
        }

    @staticmethod
    def _audit(
        command_id: UUID, outcome: str, *, registration_id: UUID | None = None
    ) -> dict[str, str | bool]:
        record: dict[str, str | bool] = {
            "actor": "fdai.runtime.isolated_executor_client",
            "command_id": str(command_id),
            "outcome": outcome,
            "execution_authority": False,
            "effect_verified": False,
        }
        if registration_id is not None:
            record["registration_id"] = str(registration_id)
        return record


def _bound_receipt_matches(
    command: SafeguardBoundExecutorCommand,
    receipt: ExecutorReceipt,
    *,
    partition_key: str,
) -> bool:
    """Bound attempts require a bundle-bearing receipt, not a legacy shadow response."""

    return (
        isinstance(receipt, ExecutorEffectReceipt)
        and receipt.received_at + _MAX_RECEIPT_CLOCK_SKEW >= command.issued_at
        and receipt_matches_command(command, receipt, partition_key=partition_key)
    )
