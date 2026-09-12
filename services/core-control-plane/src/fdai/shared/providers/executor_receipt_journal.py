"""Implementation-free receipt correlation seam for the Executor transport client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fdai.shared.contracts.models import (
    AnyExecutorCommand,
    ExecutorEffectReceipt,
    ExecutorShadowReceipt,
    SafeguardBoundExecutorCommand,
)

type ExecutorReceipt = ExecutorShadowReceipt | ExecutorEffectReceipt


class ExecutorReceiptStorageUnavailableError(RuntimeError):
    """A recoverable receipt-store failure requiring unacknowledged redelivery."""


class ExecutorReceiptRegistrationNotOwnedError(RuntimeError):
    """Exact registration ownership mismatched; cleanup MUST NOT alter another claim."""


class ExecutorReceiptRegistrationUnobservedError(RuntimeError):
    """Registration readback is not yet available; bounded recovery may read again."""


@dataclass(frozen=True, slots=True)
class BoundExecutorCommandContext:
    """Immutable correlation fields projected from validated Core evidence.

    These identifiers carry no execution, sink, release, or verification
    authority. The journal implementation validates their exact command binding.
    """

    action_id: str
    reservation_attempt: int
    source_revision: str
    execution_path: str
    safeguard_bundle_digest: str
    reservation_identity_digest: str
    evidence_identity_digest: str
    target_digest: str
    target_fence_generation: int


class ExecutorReceiptJournal(Protocol):
    """Durable correlation port; implementations own storage and closure policy."""

    async def register(
        self,
        command: SafeguardBoundExecutorCommand,
        context: BoundExecutorCommandContext,
        *,
        registration_id: UUID,
    ) -> tuple[SafeguardBoundExecutorCommand, bool]:
        """Persist before publication; return the exact command and first-claim flag.

        A false flag forbids republication. Binding, capacity, or storage errors
        propagate to the caller and prevent publication. Persist registration_id
        as correlation ownership, not execution authority, before receipt work.
        """
        ...

    async def accept(self, receipt: ExecutorReceipt, *, partition_key: str) -> bool:
        """Durably retain or reject bound receipts before consumer offset advancement.

        False means the command is not owned by this journal. Storage failures
        propagate without acknowledging delivery. Recoverable backend failures
        use ExecutorReceiptStorageUnavailableError or OSError.
        """
        ...

    async def record_not_published(
        self, command: SafeguardBoundExecutorCommand, *, registration_id: UUID
    ) -> None:
        """Retire receipt work after the owner proves publication never started.

        Retain the immutable attempt claim. This is local transport knowledge,
        not authoritative sink non-acceptance or permission to redispatch.
        Require exact command and registration readback even when register()
        raised after persistence; otherwise raise ExecutorReceiptRegistrationNotOwnedError.
        Missing readback raises ExecutorReceiptRegistrationUnobservedError for bounded retry.
        """
        ...

    async def reconcile(self) -> int:
        """Process bounded retained work against the implementation's closure source.

        Return completed work items, never dispatch a command, and never treat a
        transport receipt as independent effect or release evidence.
        """
        ...


def receipt_matches_command(
    command: AnyExecutorCommand,
    receipt: ExecutorReceipt,
    *,
    partition_key: str,
) -> bool:
    """Compare transport lineage only; a match confers no operational authority."""

    return (
        partition_key == command.partition_key
        and receipt.command_id == command.command_id
        and receipt.action_id == command.action_id
        and receipt.idempotency_key == command.idempotency_key
        and receipt.attempt == command.attempt
        and receipt.action_payload_digest == command.action_payload_digest
        and receipt.requested_mode is command.requested_mode
        and receipt.audit_ref in {None, f"action:{command.action_id}"}
        and (
            not isinstance(command, SafeguardBoundExecutorCommand)
            or isinstance(receipt, ExecutorShadowReceipt)
            or (
                isinstance(receipt, ExecutorEffectReceipt)
                and receipt.schema_version == "1.1.0"
                and receipt.safeguard_proof_bundle_digest == command.safeguard_proof_bundle_digest
            )
        )
    )
