"""Provider-neutral lifecycle contract for governed execution backends."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.execution_backend.profiles import ExecutionBackendProfile

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ExecutionStatus(StrEnum):
    PLANNED = "planned"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AMBIGUOUS = "ambiguous"

    @property
    def terminal(self) -> bool:
        return self in {
            self.SUCCEEDED,
            self.FAILED,
            self.CANCELLED,
            self.AMBIGUOUS,
        }


class ExecutionHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ExecutionCleanupState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    PROVIDER_RETENTION = "provider_retention"


class ExecutionAttemptOperation(StrEnum):
    SUBMIT = "submit"
    STATUS = "status"
    CANCEL = "cancel"
    COLLECT_RECEIPT = "collect_receipt"
    CLEANUP = "cleanup"


@dataclass(frozen=True, slots=True)
class ExecutionOwnerTrace:
    """Correlation evidence from Thor's already-governed dispatch path."""

    event_ref: str
    action_ref: str
    correlation_ref: str
    executor_role: str = "Thor"

    def __post_init__(self) -> None:
        for value in (self.event_ref, self.action_ref, self.correlation_ref):
            if not value or len(value) > 256 or "\x00" in value:
                raise ValueError("execution owner trace values MUST be bounded")
        if self.executor_role != "Thor":
            raise ValueError("execution submissions MUST retain Thor as executor owner")


@dataclass(frozen=True, slots=True)
class ExecutionBackendRequest:
    """Governed request handed to a backend after judgment and approval."""

    workload_id: str
    idempotency_key: str
    artifact_digest: str
    profile_id: str
    profile_version: str
    owner_trace: ExecutionOwnerTrace
    stop_condition: str
    audit_ref: str
    scope_ref: str
    region: str
    payload: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.workload_id) is None:
            raise ValueError("workload_id MUST be a lowercase dotted identifier")
        if not self.idempotency_key or len(self.idempotency_key) > 200:
            raise ValueError("idempotency_key MUST be a bounded non-empty string")
        if _DIGEST.fullmatch(self.artifact_digest) is None:
            raise ValueError("artifact_digest MUST be a lowercase SHA-256 digest")
        if _IDENTIFIER.fullmatch(self.profile_id) is None:
            raise ValueError("profile_id MUST be a lowercase dotted identifier")
        for name, value, limit in (
            ("profile_version", self.profile_version, 64),
            ("stop_condition", self.stop_condition, 1_024),
            ("audit_ref", self.audit_ref, 512),
            ("scope_ref", self.scope_ref, 512),
            ("region", self.region, 128),
        ):
            if not value or len(value) > limit or "\x00" in value or "\n" in value:
                raise ValueError(f"{name} MUST be a bounded non-empty string")


@dataclass(frozen=True, slots=True)
class ExecutionBackendPlan:
    plan_ref: str
    backend_kind: str
    request: ExecutionBackendRequest
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.plan_ref or len(self.plan_ref) > 1_024:
            raise ValueError("plan_ref MUST be bounded")
        if not self.backend_kind or len(self.backend_kind) > 64:
            raise ValueError("backend_kind MUST be bounded")
        if self.created_at.tzinfo is None:
            raise ValueError("plan created_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ExecutionBackendReceipt:
    status: ExecutionStatus
    submission_ref: str
    receipt_ref: str
    detail: str
    already_existed: bool = False
    output_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.submission_ref or len(self.submission_ref) > 2_048:
            raise ValueError("submission_ref MUST be bounded")
        if not self.receipt_ref or len(self.receipt_ref) > 2_048:
            raise ValueError("receipt_ref MUST be bounded")
        if len(self.detail) > 2_048:
            raise ValueError("receipt detail MUST be bounded")
        if self.output_digest is not None and _DIGEST.fullmatch(self.output_digest) is None:
            raise ValueError("output_digest MUST be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ExecutionBackendCapabilities:
    backend_kind: str
    supports_status: bool
    supports_cancel: bool
    supports_receipt: bool
    supports_cleanup: bool
    durable_provider_state: bool


@dataclass(frozen=True, slots=True)
class ExecutionBackendHealth:
    state: ExecutionHealthState
    checked_at: datetime
    detail: str


@dataclass(frozen=True, slots=True)
class ExecutionCleanupResult:
    state: ExecutionCleanupState
    detail: str


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    idempotency_key: str
    sequence: int
    operation: ExecutionAttemptOperation
    status: ExecutionStatus
    detail: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ExecutionLedgerRecord:
    idempotency_key: str
    workload_id: str
    artifact_digest: str
    profile_id: str
    profile_version: str
    backend_kind: str
    owner_trace: ExecutionOwnerTrace
    stop_condition: str
    audit_ref: str
    scope_ref: str
    region: str
    status: ExecutionStatus
    submission_ref: str | None
    receipt_ref: str | None
    detail: str
    cancel_requested: bool
    cleanup_state: ExecutionCleanupState
    created_at: datetime
    updated_at: datetime
    retention_until: datetime
    revision: int = 0


class ExecutionBackendError(RuntimeError):
    """A backend operation did not return trustworthy state."""


@runtime_checkable
class ExecutionBackend(Protocol):
    async def plan(
        self,
        request: ExecutionBackendRequest,
        *,
        profile: ExecutionBackendProfile,
    ) -> ExecutionBackendPlan: ...

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt: ...

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt: ...

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt: ...

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt: ...

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult: ...

    async def capabilities(self) -> ExecutionBackendCapabilities: ...

    async def health(self) -> ExecutionBackendHealth: ...


@runtime_checkable
class ExecutionSubmissionLedger(Protocol):
    async def create(self, record: ExecutionLedgerRecord) -> ExecutionLedgerRecord: ...

    async def get(self, idempotency_key: str) -> ExecutionLedgerRecord | None: ...

    async def update(
        self,
        record: ExecutionLedgerRecord,
        *,
        expected_revision: int,
    ) -> ExecutionLedgerRecord: ...

    async def append_attempt(self, attempt: ExecutionAttempt) -> None: ...

    async def attempts(self, idempotency_key: str) -> tuple[ExecutionAttempt, ...]: ...


__all__ = [
    "ExecutionAttempt",
    "ExecutionAttemptOperation",
    "ExecutionBackend",
    "ExecutionBackendCapabilities",
    "ExecutionBackendError",
    "ExecutionBackendHealth",
    "ExecutionBackendPlan",
    "ExecutionBackendReceipt",
    "ExecutionBackendRequest",
    "ExecutionCleanupResult",
    "ExecutionCleanupState",
    "ExecutionHealthState",
    "ExecutionLedgerRecord",
    "ExecutionOwnerTrace",
    "ExecutionStatus",
    "ExecutionSubmissionLedger",
]
