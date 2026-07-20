"""Provider-neutral contracts for continuing scheduled results in conversation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

_MAX_ID = 256
_MAX_SUMMARY = 100_000
_MAX_EVIDENCE_REFS = 64


class ContinuationMode(StrEnum):
    NONE = "none"
    ORIGIN_THREAD = "origin_thread"
    DEDICATED_THREAD = "dedicated_thread"


class ContinuationAudience(StrEnum):
    DIRECT = "direct"
    BROADCAST = "broadcast"


class ContinuationAnchorState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ScheduledResultOrigin:
    channel_kind: str
    channel_ref: str
    conversation_ref: str
    thread_ref: str | None = None
    audience: ContinuationAudience = ContinuationAudience.DIRECT

    def __post_init__(self) -> None:
        _identifier("channel_kind", self.channel_kind)
        _identifier("channel_ref", self.channel_ref)
        _identifier("conversation_ref", self.conversation_ref)
        if self.thread_ref is not None:
            _identifier("thread_ref", self.thread_ref)


@dataclass(frozen=True, slots=True)
class ScheduledConversationAnchor:
    anchor_id: str
    task_id: str
    run_id: str
    owner_principal_id: str
    scope_ref: str
    mode: ContinuationMode
    origin: ScheduledResultOrigin
    result_digest: str
    result_summary: str
    evidence_refs: tuple[str, ...]
    observation_started_at: datetime
    observation_ended_at: datetime
    created_at: datetime
    expires_at: datetime
    state: ContinuationAnchorState = ContinuationAnchorState.ACTIVE

    def __post_init__(self) -> None:
        for name, value in (
            ("anchor_id", self.anchor_id),
            ("task_id", self.task_id),
            ("run_id", self.run_id),
            ("owner_principal_id", self.owner_principal_id),
            ("scope_ref", self.scope_ref),
        ):
            _identifier(name, value)
        if self.mode is ContinuationMode.NONE:
            raise ValueError("continuation anchors require an enabled continuation mode")
        if self.origin.audience is ContinuationAudience.BROADCAST:
            raise ValueError("broadcast scheduled results cannot be continuable")
        if len(self.result_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.result_digest
        ):
            raise ValueError("result_digest MUST be a lowercase SHA-256 digest")
        if not self.result_summary.strip() or len(self.result_summary) > _MAX_SUMMARY:
            raise ValueError("result_summary MUST be bounded non-empty text")
        for ref in self.evidence_refs:
            _identifier("evidence_ref", ref)
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS or len(set(self.evidence_refs)) != len(
            self.evidence_refs
        ):
            raise ValueError("evidence_refs MUST contain <= 64 unique values")
        for timestamp_name, timestamp in (
            ("observation_started_at", self.observation_started_at),
            ("observation_ended_at", self.observation_ended_at),
            ("created_at", self.created_at),
            ("expires_at", self.expires_at),
        ):
            _aware(timestamp_name, timestamp)
        if self.observation_ended_at < self.observation_started_at:
            raise ValueError("observation_ended_at MUST be >= observation_started_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at MUST be after created_at")


class ScheduledConversationAnchorStore(Protocol):
    async def create(self, anchor: ScheduledConversationAnchor) -> ScheduledConversationAnchor: ...

    async def get(self, anchor_id: str) -> ScheduledConversationAnchor | None: ...

    async def expire(
        self, *, anchor_id: str, expected_state: ContinuationAnchorState
    ) -> ScheduledConversationAnchor | None: ...

    async def list_for_principal(
        self, *, principal_id: str, limit: int = 100
    ) -> tuple[ScheduledConversationAnchor, ...]: ...


class ScheduledContinuationDelivery(Protocol):
    async def deliver(self, anchor: ScheduledConversationAnchor) -> object: ...


def anchor_id_for_run(*, task_id: str, run_id: str) -> str:
    _identifier("task_id", task_id)
    _identifier("run_id", run_id)
    digest = hashlib.sha256(f"{task_id}:{run_id}".encode()).hexdigest()[:24]
    return f"scheduled-anchor-{digest}"


def scheduled_result_fact_text(anchor: ScheduledConversationAnchor) -> str:
    """Render bounded provenance plus result data without instruction authority."""
    evidence = ",".join(anchor.evidence_refs) or "none"
    return (
        f"[scheduled-result run={anchor.run_id} "
        f"window={anchor.observation_started_at.isoformat()}.."
        f"{anchor.observation_ended_at.isoformat()} digest={anchor.result_digest} "
        f"evidence={evidence}] {anchor.result_summary}"
    )


def _identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_ID or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "ContinuationAnchorState",
    "ContinuationAudience",
    "ContinuationMode",
    "ScheduledConversationAnchor",
    "ScheduledConversationAnchorStore",
    "ScheduledContinuationDelivery",
    "ScheduledResultOrigin",
    "anchor_id_for_run",
    "scheduled_result_fact_text",
]
