"""Durable, authority-free Saga handoff checkpoint journal."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from fdai.shared.providers.state_store import StateStore

_CLAIM_BUCKET = "handoff_escalation_claims"
_CHECKPOINT_BUCKET = "handoff_escalation_mutations"
_RECEIPT_BUCKET = "handoff_escalation_receipts"
_STATE_PREFIX = "pantheon/saga/handoff"


class LocalHandoffStateStore(Protocol):
    def get(self, bucket: str, key: str) -> Any | None: ...

    def put(self, bucket: str, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class HandoffIssueCheckpoint:
    fingerprint: str
    correlation_id: str
    issue_number: int
    created: bool
    occurrence_count: int
    audit_recorded: bool = False
    published: bool = False

    def result(self) -> dict[str, Any]:
        return {
            "issue_number": self.issue_number,
            "created": self.created,
            "occurrence_count": self.occurrence_count,
        }

    def with_audit_recorded(self) -> HandoffIssueCheckpoint:
        return replace(self, audit_recorded=True)

    def with_published(self) -> HandoffIssueCheckpoint:
        return replace(self, published=True)

    def to_state(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "fingerprint": self.fingerprint,
            "correlation_id": self.correlation_id,
            "issue_number": self.issue_number,
            "created": self.created,
            "occurrence_count": self.occurrence_count,
            "audit_recorded": self.audit_recorded,
            "published": self.published,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> HandoffIssueCheckpoint:
        issue_number = value.get("issue_number")
        occurrence_count = value.get("occurrence_count")
        created = value.get("created")
        audit_recorded = value.get("audit_recorded")
        published = value.get("published")
        if (
            value.get("schema_version") != "1.0.0"
            or not isinstance(value.get("fingerprint"), str)
            or not value["fingerprint"]
            or not isinstance(value.get("correlation_id"), str)
            or not value["correlation_id"]
            or not isinstance(issue_number, int)
            or isinstance(issue_number, bool)
            or issue_number < 1
            or not isinstance(occurrence_count, int)
            or isinstance(occurrence_count, bool)
            or occurrence_count < 1
            or not isinstance(created, bool)
            or not isinstance(audit_recorded, bool)
            or not isinstance(published, bool)
        ):
            raise ValueError("durable handoff checkpoint is malformed")
        return cls(
            fingerprint=str(value["fingerprint"]),
            correlation_id=str(value["correlation_id"]),
            issue_number=issue_number,
            created=created,
            occurrence_count=occurrence_count,
            audit_recorded=audit_recorded,
            published=published,
        )


@dataclass(frozen=True, slots=True)
class HandoffCompletionReceipt:
    escalation_id: str
    fingerprint: str
    correlation_id: str
    issue_number: int
    created: bool
    occurrence_count: int

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> HandoffCompletionReceipt:
        issue_number = value.get("issue_number")
        occurrence_count = value.get("occurrence_count")
        created = value.get("created")
        if (
            value.get("schema_version") != "1.0.0"
            or not isinstance(value.get("escalation_id"), str)
            or not value["escalation_id"]
            or not isinstance(value.get("fingerprint"), str)
            or not value["fingerprint"]
            or not isinstance(value.get("correlation_id"), str)
            or not value["correlation_id"]
            or not isinstance(issue_number, int)
            or isinstance(issue_number, bool)
            or issue_number < 1
            or not isinstance(occurrence_count, int)
            or isinstance(occurrence_count, bool)
            or occurrence_count < 1
            or not isinstance(created, bool)
        ):
            raise ValueError("durable handoff completion receipt is malformed")
        return cls(
            escalation_id=str(value["escalation_id"]),
            fingerprint=str(value["fingerprint"]),
            correlation_id=str(value["correlation_id"]),
            issue_number=issue_number,
            created=created,
            occurrence_count=occurrence_count,
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "escalation_id": self.escalation_id,
            "fingerprint": self.fingerprint,
            "correlation_id": self.correlation_id,
            "issue_number": self.issue_number,
            "created": self.created,
            "occurrence_count": self.occurrence_count,
        }


class SagaHandoffJournal:
    """Persist replay checkpoints without making issue or audit decisions."""

    def __init__(
        self,
        *,
        local_store: LocalHandoffStateStore,
        durable_store: StateStore | None,
    ) -> None:
        self._local = local_store
        self._durable = durable_store

    async def is_complete(
        self,
        *,
        escalation_id: str,
        fingerprint: str,
        correlation_id: str,
    ) -> bool:
        if self._durable is not None:
            stored = await self._durable.read_state(_state_key(escalation_id, "receipt"))
        else:
            stored = self._local.get(_RECEIPT_BUCKET, escalation_id)
        if stored is None:
            return False
        if not isinstance(stored, Mapping):
            raise ValueError("durable handoff completion receipt is malformed")
        receipt = HandoffCompletionReceipt.from_state(stored)
        if (
            receipt.escalation_id != escalation_id
            or receipt.fingerprint != fingerprint
            or receipt.correlation_id != correlation_id
        ):
            raise ValueError("handoff escalation id conflicts with its completion receipt")
        return True

    async def claim(
        self,
        *,
        escalation_id: str,
        fingerprint: str,
        correlation_id: str,
        operation_id: str,
    ) -> None:
        claim = {
            "schema_version": "1.0.0",
            "escalation_id": escalation_id,
            "fingerprint": fingerprint,
            "correlation_id": correlation_id,
            "operation_id": operation_id,
        }
        if self._durable is not None:
            key = _state_key(escalation_id, "claim")
            created = await self._durable.write_state_if_absent(key, claim)
            stored = claim if created else await self._durable.read_state(key)
        else:
            stored = self._local.get(_CLAIM_BUCKET, escalation_id)
            if stored is None:
                self._local.put(_CLAIM_BUCKET, escalation_id, claim)
                stored = claim
        if not isinstance(stored, Mapping) or dict(stored) != claim:
            raise ValueError("handoff escalation id conflicts with its durable claim")

    async def read_checkpoint(self, escalation_id: str) -> HandoffIssueCheckpoint | None:
        if self._durable is not None:
            stored = await self._durable.read_state(_state_key(escalation_id, "checkpoint"))
            return HandoffIssueCheckpoint.from_state(stored) if stored is not None else None
        stored = self._local.get(_CHECKPOINT_BUCKET, escalation_id)
        if stored is None:
            return None
        if not isinstance(stored, HandoffIssueCheckpoint):
            raise ValueError("handoff mutation checkpoint is malformed")
        return stored

    async def write_checkpoint(
        self,
        escalation_id: str,
        checkpoint: HandoffIssueCheckpoint,
    ) -> None:
        if self._durable is not None:
            await self._durable.write_state(
                _state_key(escalation_id, "checkpoint"),
                checkpoint.to_state(),
            )
        else:
            self._local.put(_CHECKPOINT_BUCKET, escalation_id, checkpoint)

    async def complete(
        self,
        escalation_id: str,
        checkpoint: HandoffIssueCheckpoint,
    ) -> None:
        receipt = HandoffCompletionReceipt(
            escalation_id=escalation_id,
            fingerprint=checkpoint.fingerprint,
            correlation_id=checkpoint.correlation_id,
            issue_number=checkpoint.issue_number,
            created=checkpoint.created,
            occurrence_count=checkpoint.occurrence_count,
        ).to_state()
        if self._durable is not None:
            key = _state_key(escalation_id, "receipt")
            created = await self._durable.write_state_if_absent(key, receipt)
            if not created:
                stored = await self._durable.read_state(key)
                if stored != receipt:
                    raise RuntimeError("handoff completion receipt collision")
        self._local.put(_RECEIPT_BUCKET, escalation_id, receipt)


def _state_key(escalation_id: str, suffix: str) -> str:
    digest = hashlib.sha256(escalation_id.encode("utf-8")).hexdigest()
    return f"{_STATE_PREFIX}/{digest}/{suffix}"


__all__ = ["HandoffIssueCheckpoint", "SagaHandoffJournal"]
