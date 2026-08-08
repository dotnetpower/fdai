"""Narrow provider ports consumed by the isolated Executor service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PendingExecutorReceipt:
    """One committed receipt awaiting broker acknowledgement."""

    receipt_id: UUID
    partition_key: str
    payload: Mapping[str, Any]
    command_id: str | None
    command_offset: int | None


class ExecutorReceiptOutbox(Protocol):
    """Durably stage and acknowledge Executor receipt publication."""

    async def commit_receipt(
        self,
        receipt_id: UUID,
        partition_key: str,
        payload: Mapping[str, Any],
        *,
        command_id: str,
        command_offset: int | None,
    ) -> None: ...

    async def claim_receipts(self, *, limit: int) -> tuple[PendingExecutorReceipt, ...]: ...

    async def mark_receipt_published(self, receipt_id: UUID) -> None: ...


class ExecutorStateStore(Protocol):
    """Persist executor audit records and atomic durable attempt claims."""

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None: ...

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool: ...

    async def assert_schema(self) -> None: ...

    async def commit_receipt(
        self,
        receipt_id: UUID,
        partition_key: str,
        payload: Mapping[str, Any],
        *,
        command_id: str,
        command_offset: int | None,
    ) -> None: ...

    async def claim_receipts(self, *, limit: int) -> tuple[PendingExecutorReceipt, ...]: ...

    async def mark_receipt_published(self, receipt_id: UUID) -> None: ...


__all__ = ["ExecutorReceiptOutbox", "ExecutorStateStore", "PendingExecutorReceipt"]
