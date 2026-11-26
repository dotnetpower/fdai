"""Typed per-user conversation policies and proactive briefing contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledResultOrigin,
)


class ConversationPolicyKind(StrEnum):
    OPENING_BRIEFING = "opening_briefing"
    RESPONSE_DEFAULTS = "response_defaults"


class BriefingKind(StrEnum):
    MAJOR_ISSUES = "major_issues"
    OPERATIONS_DIGEST = "operations_digest"


class BriefingDeliveryMode(StrEnum):
    IN_APP = "in_app"
    TEAMS = "teams"
    EMAIL = "email"


class BriefingRunStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BriefingSpec:
    kind: BriefingKind = BriefingKind.MAJOR_ISSUES
    lookback_seconds: int = 86_400
    minimum_severity: str = "high"
    categories: tuple[str, ...] = ()
    max_items: int = 5
    include_pending_approvals: bool = True
    include_failed_actions: bool = True
    scope_ref: str | None = None

    def __post_init__(self) -> None:
        if not 300 <= self.lookback_seconds <= 31_536_000:
            raise ValueError("BriefingSpec.lookback_seconds MUST be in [300, 31536000]")
        if self.minimum_severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("BriefingSpec.minimum_severity is invalid")
        if not 1 <= self.max_items <= 50:
            raise ValueError("BriefingSpec.max_items MUST be in [1, 50]")
        if self.scope_ref is not None and not self.scope_ref.strip():
            raise ValueError("BriefingSpec.scope_ref MUST be non-empty when set")


@dataclass(frozen=True, slots=True)
class ConversationPolicyRecord:
    policy_id: str
    principal_id: str
    kind: ConversationPolicyKind
    enabled: bool
    revision: int
    confirmed_at: datetime
    source_turn_id: str
    briefing_spec: BriefingSpec | None = None
    response_defaults: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("ConversationPolicyRecord.policy_id", self.policy_id)
        _require_text("ConversationPolicyRecord.principal_id", self.principal_id)
        _require_text("ConversationPolicyRecord.source_turn_id", self.source_turn_id)
        _require_aware("ConversationPolicyRecord.confirmed_at", self.confirmed_at)
        if self.revision < 0:
            raise ValueError("ConversationPolicyRecord.revision MUST be >= 0")
        if self.kind is ConversationPolicyKind.OPENING_BRIEFING:
            if self.briefing_spec is None or self.response_defaults:
                raise ValueError("opening_briefing requires only briefing_spec")
        elif self.briefing_spec is not None:
            raise ValueError("response_defaults MUST NOT declare briefing_spec")
        allowed_defaults = {"verbosity", "answer_language"}
        unknown = set(self.response_defaults) - allowed_defaults
        if unknown:
            raise ValueError(
                "ConversationPolicyRecord.response_defaults has unsupported keys: "
                + ", ".join(sorted(unknown))
            )


@dataclass(frozen=True, slots=True)
class BriefingSubscription:
    subscription_id: str
    principal_id: str
    name: str
    spec: BriefingSpec
    cron_expression: str
    timezone: str
    delivery_modes: tuple[BriefingDeliveryMode, ...]
    enabled: bool
    next_run_at: datetime
    created_at: datetime
    revision: int = 0
    channel_binding_ref: str | None = None
    max_lateness_seconds: int = 3600
    continuation_mode: ContinuationMode = ContinuationMode.NONE
    continuation_origin: ScheduledResultOrigin | None = None
    continuation_ttl_seconds: int = 604_800

    def __post_init__(self) -> None:
        _require_text("BriefingSubscription.subscription_id", self.subscription_id)
        _require_text("BriefingSubscription.principal_id", self.principal_id)
        _require_text("BriefingSubscription.name", self.name)
        if len(self.cron_expression.split()) != 5 or not croniter.is_valid(
            self.cron_expression, strict=True
        ):
            raise ValueError("BriefingSubscription.cron_expression MUST be strict 5-field cron")
        _validate_timezone(self.timezone)
        if not self.delivery_modes:
            raise ValueError("BriefingSubscription.delivery_modes MUST be non-empty")
        if (
            any(mode is not BriefingDeliveryMode.IN_APP for mode in self.delivery_modes)
            and self.channel_binding_ref is None
        ):
            raise ValueError("external delivery requires channel_binding_ref")
        _require_aware("BriefingSubscription.next_run_at", self.next_run_at)
        _require_aware("BriefingSubscription.created_at", self.created_at)
        if not 0 <= self.max_lateness_seconds <= 604_800:
            raise ValueError("BriefingSubscription.max_lateness_seconds MUST be in [0, 604800]")
        if self.revision < 0:
            raise ValueError("BriefingSubscription.revision MUST be >= 0")
        if not 300 <= self.continuation_ttl_seconds <= 31_536_000:
            raise ValueError("continuation_ttl_seconds MUST be in [300, 31536000]")
        if self.continuation_mode is ContinuationMode.NONE:
            if self.continuation_origin is not None:
                raise ValueError("continuation origin requires an enabled continuation mode")
        else:
            if self.continuation_origin is None:
                raise ValueError("enabled continuation requires immutable origin metadata")
            if self.spec.scope_ref is None:
                raise ValueError("enabled continuation requires an explicit briefing scope_ref")


@dataclass(frozen=True, slots=True)
class BriefingRun:
    run_id: str
    subscription_id: str | None
    principal_id: str
    conversation_id: str | None
    scheduled_for: datetime
    started_at: datetime
    status: BriefingRunStatus
    idempotency_key: str
    title: str
    body_markdown: str
    item_count: int = 0
    evidence_refs: tuple[str, ...] = ()
    source_errors: tuple[str, ...] = ()
    continuation_mode: ContinuationMode = ContinuationMode.NONE
    continuation_origin: ScheduledResultOrigin | None = None
    result_digest: str | None = None

    def __post_init__(self) -> None:
        _require_text("BriefingRun.run_id", self.run_id)
        _require_text("BriefingRun.principal_id", self.principal_id)
        _require_text("BriefingRun.idempotency_key", self.idempotency_key)
        _require_text("BriefingRun.title", self.title)
        _require_text("BriefingRun.body_markdown", self.body_markdown)
        if len(self.title) > 200:
            raise ValueError("BriefingRun.title MUST be <= 200 characters")
        if len(self.body_markdown) > 100_000:
            raise ValueError("BriefingRun.body_markdown MUST be <= 100000 characters")
        _require_aware("BriefingRun.scheduled_for", self.scheduled_for)
        _require_aware("BriefingRun.started_at", self.started_at)
        if self.item_count < 0:
            raise ValueError("BriefingRun.item_count MUST be >= 0")
        if self.subscription_id is None and self.conversation_id is None:
            raise ValueError("BriefingRun requires subscription_id or conversation_id")
        if self.continuation_mode is ContinuationMode.NONE:
            if self.continuation_origin is not None or self.result_digest is not None:
                raise ValueError("continuation metadata requires an enabled continuation mode")
        else:
            if self.continuation_origin is None:
                raise ValueError("enabled continuation requires immutable origin metadata")
            if (
                self.result_digest is None
                or len(self.result_digest) != 64
                or any(char not in "0123456789abcdef" for char in self.result_digest)
            ):
                raise ValueError("continuable briefing run requires a SHA-256 result_digest")


class BriefingConflictError(RuntimeError):
    """A policy, subscription, or run conflicts with a durable record."""


@runtime_checkable
class ConversationPolicyStore(Protocol):
    async def put(
        self, record: ConversationPolicyRecord, *, expected_revision: int | None = None
    ) -> ConversationPolicyRecord: ...

    async def list_for_principal(
        self, *, principal_id: str
    ) -> Sequence[ConversationPolicyRecord]: ...

    async def delete(
        self,
        *,
        principal_id: str,
        policy_id: str,
        expected_revision: int,
    ) -> bool: ...


@runtime_checkable
class BriefingSubscriptionStore(Protocol):
    async def create(self, record: BriefingSubscription) -> BriefingSubscription: ...

    async def list_for_principal(self, *, principal_id: str) -> Sequence[BriefingSubscription]: ...

    async def claim_due(
        self, *, now: datetime, limit: int, lease_owner: str, lease_seconds: int
    ) -> Sequence[BriefingSubscription]: ...

    async def advance(
        self,
        *,
        subscription_id: str,
        principal_id: str,
        expected_revision: int,
        next_run_at: datetime,
    ) -> BriefingSubscription: ...

    async def delete(
        self,
        *,
        principal_id: str,
        subscription_id: str,
        expected_revision: int,
    ) -> bool: ...


@runtime_checkable
class BriefingRunStore(Protocol):
    async def create(self, run: BriefingRun) -> BriefingRun: ...

    async def list_for_principal(
        self, *, principal_id: str, limit: int = 100
    ) -> Sequence[BriefingRun]: ...

    async def purge_before(
        self,
        *,
        before: datetime,
        limit: int = 100,
    ) -> Sequence[BriefingRun]: ...


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone {value!r}") from exc


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} MUST be non-empty")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "BriefingConflictError",
    "BriefingDeliveryMode",
    "BriefingKind",
    "BriefingRun",
    "BriefingRunStatus",
    "BriefingRunStore",
    "BriefingSpec",
    "BriefingSubscription",
    "BriefingSubscriptionStore",
    "ConversationPolicyKind",
    "ConversationPolicyRecord",
    "ConversationPolicyStore",
]
