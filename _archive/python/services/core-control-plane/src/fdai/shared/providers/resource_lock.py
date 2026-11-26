"""Resource lock - per-resource serialization seam.

The executor serializes actions that mutate the same resource (the
per-resource ordering rule in
``architecture.instructions.md § Idempotency, Ordering, and Replay``).
The in-process default (:class:`fdai.core.executor.lock.ResourceLockManager`)
is correct for a single replica, but the control plane is event-driven +
scale-to-zero: under KEDA more than one replica can consume the same
partition, and an in-memory lock cannot serialize across replicas. This
Protocol is the seam that lets the composition root bind a *distributed*
lock (Postgres advisory lock) so per-resource mutual exclusion holds
across the whole deployment, not just within one process.

Async by contract - a distributed backend acquires the lock over I/O
(a Postgres session advisory lock), which would otherwise block the event
loop. The in-process implementation satisfies the same async-context
shape with no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol, Self, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_REVISION = re.compile(r"^commit:[a-f0-9]{40}(?:[a-f0-9]{24})?$")
MAX_LOCK_ASSESSMENT_TTL = timedelta(seconds=5)


@dataclass(frozen=True, slots=True)
class ResourceLockAcquisitionRequest:
    """Canonical caller context for an adapter-owned evidenced acquisition."""

    schema_version: Literal["1.0.0"]
    target_ref: str
    lock_key: str
    target_digest: str
    action_digest: str
    attempt: int
    producer_id: str
    producer_version: str
    source_revision: str
    request_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError(
                f"unsupported resource lock request schema version: {self.schema_version}"
            )
        if self.execution_authority is not False:
            raise ValueError("resource lock request MUST NOT grant execution authority")
        _validate_target_ref(self.target_ref)
        _validate_resource_lock_key(self.lock_key)
        if self.lock_key != resource_lock_key(
            self.target_ref
        ) or self.target_digest != resource_lock_target_digest(self.target_ref):
            raise ValueError("resource lock request target identity mismatched")
        _validate_text("producer_id", self.producer_id)
        _validate_text("producer_version", self.producer_version)
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("resource lock request attempt MUST be a positive integer")
        for digest in (self.target_digest, self.action_digest, self.request_digest):
            if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
                raise ValueError("resource lock request digest fields MUST be SHA-256")
        if (
            type(self.source_revision) is not str
            or _REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("resource lock request source revision MUST be canonical")
        if self.request_digest != _content_digest(self, "resource-lock-request"):
            raise ValueError("resource lock request digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        target_ref: str,
        action_digest: str,
        attempt: int,
        producer_id: str,
        producer_version: str,
        source_revision: str,
    ) -> ResourceLockAcquisitionRequest:
        """Create one request without accepting adapter-owned evidence fields."""

        if cls is not ResourceLockAcquisitionRequest:
            raise TypeError("resource lock request factory does not support subclasses")
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "target_ref": target_ref,
            "lock_key": resource_lock_key(target_ref),
            "target_digest": resource_lock_target_digest(target_ref),
            "action_digest": action_digest,
            "attempt": attempt,
            "producer_id": producer_id,
            "producer_version": producer_version,
            "source_revision": source_revision,
            "execution_authority": False,
        }
        payload["request_digest"] = _payload_digest(payload, "resource-lock-request")
        return cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ResourceLockAcquisitionReceipt:
    """Historical provider-attested lock acquisition with no authority."""

    schema_version: Literal["1.0.0"]
    lock_key: str
    target_digest: str
    action_digest: str
    attempt: int
    provider_id: str
    provider_version: str
    producer_id: str
    producer_version: str
    owner_token_digest: str
    fencing_generation: int | None
    session_identity: str | None
    provider_attestation_digest: str
    trust_anchor_id: str
    acquired_at: datetime
    valid_until: datetime | None
    source_revision: str
    request_digest: str
    receipt_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError(
                f"unsupported resource lock receipt schema version: {self.schema_version}"
            )
        if self.execution_authority is not False:
            raise ValueError("resource lock receipt MUST NOT grant execution authority")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("resource lock receipt attempt MUST be a positive integer")
        _validate_common(self)
        lease = self.fencing_generation is not None
        session = self.session_identity is not None
        if lease == session:
            raise ValueError("resource lock receipt requires exactly one lifetime form")
        if lease and (
            self.fencing_generation is None
            or type(self.fencing_generation) is not int
            or self.fencing_generation < 1
            or self.valid_until is None
            or self.valid_until <= self.acquired_at
        ):
            raise ValueError("resource lock lease lifetime is invalid")
        if session and (
            self.session_identity is None
            or type(self.session_identity) is not str
            or not self.session_identity.strip()
            or self.session_identity != self.session_identity.strip()
            or len(self.session_identity) > 512
            or self.valid_until is not None
        ):
            raise ValueError("resource lock session lifetime is invalid")
        if self.receipt_digest != _content_digest(self, "resource-lock-acquisition"):
            raise ValueError("resource lock receipt digest mismatched")

    @classmethod
    def create(cls, **values: object) -> Self:
        """Create one canonical historical acquisition receipt."""

        if cls is not ResourceLockAcquisitionReceipt:
            raise TypeError("resource lock receipt factory does not support subclasses")
        payload = dict(values)
        payload.setdefault("schema_version", "1.0.0")
        payload.setdefault("execution_authority", False)
        payload["acquired_at"] = _utc(payload.get("acquired_at"), "acquired_at")
        if payload.get("valid_until") is not None:
            payload["valid_until"] = _utc(payload.get("valid_until"), "valid_until")
        payload["receipt_digest"] = _payload_digest(
            payload,
            "resource-lock-acquisition",
        )
        return cls(**payload)  # type: ignore[arg-type]


class LockOwnershipRejectionReason(StrEnum):
    """Why historical lock acquisition is not current ownership."""

    ATTESTATION_INVALID = "attestation_invalid"
    EXPIRED = "expired"
    FENCE_MISMATCH = "fence_mismatch"
    LOCK_LOST = "lock_lost"
    SESSION_MISMATCH = "session_mismatch"
    TRUST_ANCHOR_MISMATCH = "trust_anchor_mismatch"
    VALIDITY_EXCEEDS_LOCK = "validity_exceeds_lock"


class ResourceLockReleaseState(StrEnum):
    """Terminal knowledge about release of one exact acquisition."""

    RELEASED = "released"
    LOST = "lost"
    UNKNOWN = "unknown"


_INDEPENDENT_LOCK_REJECTIONS = frozenset(
    {
        LockOwnershipRejectionReason.ATTESTATION_INVALID,
        LockOwnershipRejectionReason.LOCK_LOST,
    }
)


def _derive_lock_rejection_reasons(
    receipt: ResourceLockAcquisitionReceipt,
    *,
    current_fencing_generation: int | None,
    current_session_identity: str | None,
    trust_anchor_id: str,
    evaluated_at: datetime,
    valid_until: datetime,
    asserted_reasons: tuple[LockOwnershipRejectionReason, ...],
) -> tuple[LockOwnershipRejectionReason, ...]:
    reasons = set(asserted_reasons).intersection(_INDEPENDENT_LOCK_REJECTIONS)
    if receipt.trust_anchor_id != trust_anchor_id:
        reasons.add(LockOwnershipRejectionReason.TRUST_ANCHOR_MISMATCH)
    if receipt.fencing_generation is not None:
        if current_session_identity is not None:
            reasons.add(LockOwnershipRejectionReason.SESSION_MISMATCH)
        if current_fencing_generation != receipt.fencing_generation:
            reasons.add(LockOwnershipRejectionReason.FENCE_MISMATCH)
        if receipt.valid_until is None or evaluated_at >= receipt.valid_until:
            reasons.add(LockOwnershipRejectionReason.EXPIRED)
        elif valid_until > receipt.valid_until:
            reasons.add(LockOwnershipRejectionReason.VALIDITY_EXCEEDS_LOCK)
    else:
        if current_fencing_generation is not None:
            reasons.add(LockOwnershipRejectionReason.FENCE_MISMATCH)
        if current_session_identity != receipt.session_identity:
            reasons.add(LockOwnershipRejectionReason.SESSION_MISMATCH)
    return tuple(sorted(reasons, key=str))


@dataclass(frozen=True, slots=True)
class LiveLockOwnershipAssessment:
    """Current provider-attested lock ownership required before protected use."""

    schema_version: Literal["1.0.0"]
    acquisition_receipt: ResourceLockAcquisitionReceipt
    current_fencing_generation: int | None
    current_session_identity: str | None
    verifier_id: str
    verifier_version: str
    trust_anchor_id: str
    provider_attestation_digest: str
    evaluated_at: datetime
    valid_until: datetime
    eligible: bool
    rejection_reasons: tuple[LockOwnershipRejectionReason, ...]
    assessment_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError(
                f"unsupported live lock assessment schema version: {self.schema_version}"
            )
        if type(self.acquisition_receipt) is not ResourceLockAcquisitionReceipt:
            raise ValueError("live lock assessment requires a validated acquisition receipt")
        if self.execution_authority is not False:
            raise ValueError("live lock assessment MUST NOT grant execution authority")
        _validate_text("verifier_id", self.verifier_id)
        _validate_text("verifier_version", self.verifier_version)
        _validate_text("trust_anchor_id", self.trust_anchor_id)
        if self.current_fencing_generation is not None and (
            type(self.current_fencing_generation) is not int or self.current_fencing_generation < 1
        ):
            raise ValueError("live lock assessment fencing generation MUST be a positive integer")
        if self.current_session_identity is not None:
            _validate_text("current_session_identity", self.current_session_identity)
            if self.current_session_identity != self.current_session_identity.strip():
                raise ValueError("live lock assessment session identity MUST be canonical")
        _validate_utc("evaluated_at", self.evaluated_at)
        _validate_utc("valid_until", self.valid_until)
        if type(self.rejection_reasons) is not tuple or any(
            type(reason) is not LockOwnershipRejectionReason for reason in self.rejection_reasons
        ):
            raise ValueError("live lock rejection reasons MUST use the canonical enum")
        if self.rejection_reasons != tuple(sorted(set(self.rejection_reasons), key=str)):
            raise ValueError("live lock rejection reasons MUST be unique and ordered")
        if self.evaluated_at < self.acquisition_receipt.acquired_at:
            raise ValueError("live lock assessment cannot predate lock acquisition")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("live lock assessment validity MUST follow evaluation")
        if self.valid_until - self.evaluated_at > MAX_LOCK_ASSESSMENT_TTL:
            raise ValueError("live lock assessment validity exceeds the maximum TTL")
        expected_reasons = _derive_lock_rejection_reasons(
            self.acquisition_receipt,
            current_fencing_generation=self.current_fencing_generation,
            current_session_identity=self.current_session_identity,
            trust_anchor_id=self.trust_anchor_id,
            evaluated_at=self.evaluated_at,
            valid_until=self.valid_until,
            asserted_reasons=self.rejection_reasons,
        )
        if self.rejection_reasons != expected_reasons:
            raise ValueError("live lock assessment rejection reasons mismatched state")
        expected_eligibility = not expected_reasons
        if type(self.eligible) is not bool or self.eligible is not expected_eligibility:
            raise ValueError("live lock assessment eligibility mismatched reasons")
        if (
            type(self.provider_attestation_digest) is not str
            or _DIGEST.fullmatch(self.provider_attestation_digest) is None
        ):
            raise ValueError("live lock assessment digest fields MUST be SHA-256")
        if (
            type(self.assessment_digest) is not str
            or _DIGEST.fullmatch(self.assessment_digest) is None
        ):
            raise ValueError("live lock assessment digest MUST be SHA-256")
        if self.assessment_digest != _content_digest(self, "live-lock-ownership"):
            raise ValueError("live lock assessment digest mismatched")

    @classmethod
    def create(
        cls,
        receipt: ResourceLockAcquisitionReceipt,
        *,
        current_fencing_generation: int | None,
        current_session_identity: str | None,
        verifier_id: str,
        verifier_version: str,
        trust_anchor_id: str,
        provider_attestation_digest: str,
        evaluated_at: datetime,
        valid_until: datetime,
        rejection_reasons: tuple[LockOwnershipRejectionReason, ...] = (),
    ) -> Self:
        """Create a current assessment bound to one historical receipt."""

        if cls is not LiveLockOwnershipAssessment:
            raise TypeError("live lock assessment factory does not support subclasses")
        if type(rejection_reasons) is not tuple or any(
            type(reason) is not LockOwnershipRejectionReason for reason in rejection_reasons
        ):
            raise ValueError("live lock rejection reasons MUST use the canonical enum")
        if set(rejection_reasons).difference(_INDEPENDENT_LOCK_REJECTIONS):
            raise ValueError(
                "live lock assessment caller may assert only provider-observed reasons"
            )
        normalized_at = _utc(evaluated_at, "evaluated_at")
        normalized_until = _utc(valid_until, "valid_until")
        reasons = _derive_lock_rejection_reasons(
            receipt,
            current_fencing_generation=current_fencing_generation,
            current_session_identity=current_session_identity,
            trust_anchor_id=trust_anchor_id,
            evaluated_at=normalized_at,
            valid_until=normalized_until,
            asserted_reasons=rejection_reasons,
        )
        payload = {
            "schema_version": "1.0.0",
            "acquisition_receipt": receipt,
            "current_fencing_generation": current_fencing_generation,
            "current_session_identity": current_session_identity,
            "verifier_id": verifier_id,
            "verifier_version": verifier_version,
            "trust_anchor_id": trust_anchor_id,
            "provider_attestation_digest": provider_attestation_digest,
            "evaluated_at": normalized_at,
            "valid_until": normalized_until,
            "eligible": not reasons,
            "rejection_reasons": reasons,
            "execution_authority": False,
        }
        payload["assessment_digest"] = _payload_digest(payload, "live-lock-ownership")
        return cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ResourceLockReleaseReceipt:
    """No-authority terminal release evidence for one acquisition."""

    schema_version: Literal["1.0.0"]
    acquisition_receipt: ResourceLockAcquisitionReceipt
    state: ResourceLockReleaseState
    provider_attestation_digest: str
    observed_at: datetime | None
    recorded_at: datetime
    receipt_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported resource lock release receipt schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("resource lock release receipt MUST NOT grant authority")
        if type(self.acquisition_receipt) is not ResourceLockAcquisitionReceipt:
            raise ValueError("resource lock release requires an exact acquisition receipt")
        if type(self.state) is not ResourceLockReleaseState:
            raise ValueError("resource lock release state is invalid")
        if (
            type(self.provider_attestation_digest) is not str
            or _DIGEST.fullmatch(self.provider_attestation_digest) is None
        ):
            raise ValueError("resource lock release attestation MUST be SHA-256")
        if self.observed_at is not None:
            _validate_utc("observed_at", self.observed_at)
        if (
            self.state
            in {
                ResourceLockReleaseState.RELEASED,
                ResourceLockReleaseState.LOST,
            }
            and self.observed_at is None
        ):
            raise ValueError("known resource lock release state requires observation time")
        _validate_utc("recorded_at", self.recorded_at)
        if self.observed_at is not None and (
            self.observed_at < self.acquisition_receipt.acquired_at
            or self.observed_at > self.recorded_at
        ):
            raise ValueError("resource lock release chronology is invalid")
        if (
            self.state is not ResourceLockReleaseState.UNKNOWN
            and self.recorded_at < self.acquisition_receipt.acquired_at
        ):
            raise ValueError("resource lock release chronology is invalid")
        if type(self.receipt_digest) is not str or _DIGEST.fullmatch(self.receipt_digest) is None:
            raise ValueError("resource lock release receipt digest MUST be SHA-256")
        if self.receipt_digest != _content_digest(self, "resource-lock-release"):
            raise ValueError("resource lock release receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        acquisition_receipt: ResourceLockAcquisitionReceipt,
        state: ResourceLockReleaseState,
        provider_attestation_digest: str,
        observed_at: datetime | None,
        recorded_at: datetime,
    ) -> Self:
        """Create immutable terminal release evidence."""

        if cls is not ResourceLockReleaseReceipt:
            raise TypeError("resource lock release receipt does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "acquisition_receipt": acquisition_receipt,
            "state": state,
            "provider_attestation_digest": provider_attestation_digest,
            "observed_at": (_utc(observed_at, "observed_at") if observed_at is not None else None),
            "recorded_at": _utc(recorded_at, "recorded_at"),
            "execution_authority": False,
            "effect_verified": False,
        }
        values["receipt_digest"] = _payload_digest(
            values,
            "resource-lock-release",
        )
        return cls(**values)  # type: ignore[arg-type]


def require_current_lock_ownership(
    evidence: object,
    *,
    observed_at: datetime,
) -> LiveLockOwnershipAssessment:
    """Require eligible provider-attested ownership at one exact observation time."""

    normalized_at = _utc(observed_at, "ownership observation time")
    if type(evidence) is not LiveLockOwnershipAssessment:
        raise ValueError("historical lock acquisition is not current ownership evidence")
    if normalized_at < evidence.evaluated_at:
        raise ValueError("live lock ownership assessment is not yet current")
    if normalized_at >= evidence.valid_until:
        raise ValueError("live lock ownership assessment is stale")
    if not evidence.eligible:
        raise ValueError("live lock ownership assessment is ineligible")
    return evidence


def resource_lock_target_digest(target_ref: str) -> str:
    """Return the canonical digest bound to one logical lock target."""

    _validate_target_ref(target_ref)
    return content_digest({"target_resource_ref": target_ref})


def resource_lock_key(target_ref: str) -> str:
    """Return the canonical logical lock key for one target reference."""

    _validate_target_ref(target_ref)
    return f"fdai:resource:{target_ref}"


class HeldResourceLockLifecycle:
    """Make an escaped held-lock handle inert after loss or context exit."""

    __slots__ = ("__deactivated", "__receipt", "__request")

    def __init__(
        self,
        acquisition_request: ResourceLockAcquisitionRequest,
        acquisition_receipt: ResourceLockAcquisitionReceipt,
    ) -> None:
        if type(acquisition_request) is not ResourceLockAcquisitionRequest:
            raise ValueError("held lock lifecycle requires a validated acquisition request")
        if type(acquisition_receipt) is not ResourceLockAcquisitionReceipt:
            raise ValueError("held lock lifecycle requires a validated acquisition receipt")
        _validate_request_receipt_binding(acquisition_request, acquisition_receipt)
        self.__request = acquisition_request
        self.__receipt = acquisition_receipt
        self.__deactivated = False

    @property
    def acquisition_request(self) -> ResourceLockAcquisitionRequest:
        """Return the exact immutable request for this acquisition."""

        return self.__request

    @property
    def acquisition_receipt(self) -> ResourceLockAcquisitionReceipt:
        """Return the exact immutable receipt for this acquisition."""

        return self.__receipt

    @property
    def active(self) -> bool:
        """Whether this exact acquisition handle remains usable."""

        return self.__deactivated is False

    def deactivate(self) -> None:
        """Permanently invalidate this acquisition handle."""

        self.__deactivated = True

    def require_active(self) -> None:
        """Fail closed after release, ownership loss, or context exit."""

        if self.__deactivated is True:
            raise RuntimeError("held resource lock is no longer active")


@runtime_checkable
class HeldResourceLock(Protocol):
    """One adapter-owned evidenced acquisition valid only inside its context."""

    @property
    def acquisition_request(self) -> ResourceLockAcquisitionRequest:
        """Return immutable caller context bound to the acquisition."""
        ...

    @property
    def acquisition_receipt(self) -> ResourceLockAcquisitionReceipt:
        """Return immutable historical acquisition evidence."""
        ...

    def require_active(self) -> None:
        """Fail closed when this exact acquisition is no longer active."""
        ...

    @property
    def release_receipt(self) -> ResourceLockReleaseReceipt | None:
        """Return terminal release evidence after context exit."""
        ...

    async def assess_ownership(self) -> LiveLockOwnershipAssessment:
        """Perform a fresh adapter-timed authoritative ownership readback."""
        ...


@runtime_checkable
class EvidenceResourceLock(Protocol):
    """Explicit mutation-target locking seam with no legacy fallback."""

    @property
    def production_eligible(self) -> bool:
        """Whether this adapter can satisfy production composition."""
        ...

    def acquire_evidenced(
        self,
        request: ResourceLockAcquisitionRequest,
    ) -> AbstractAsyncContextManager[HeldResourceLock]:
        """Acquire the exact target and yield one lifecycle-bounded handle."""
        ...


def require_evidence_resource_lock(
    provider: object,
    *,
    production: bool,
) -> EvidenceResourceLock:
    """Resolve the explicit evidenced seam without adapting a legacy lock."""

    if not isinstance(provider, EvidenceResourceLock):
        raise RuntimeError("evidenced resource lock provider is unavailable")
    if production and provider.production_eligible is not True:
        raise RuntimeError("evidenced resource lock provider is not production eligible")
    return provider


@runtime_checkable
class ResourceLock(Protocol):
    """Serialize critical sections per ``resource_id``.

    ``acquire`` returns an async context manager held for the *duration
    of the action* (render + apply + audit), so a racing action on the
    same resource - in this process or another replica - waits. The lock
    MUST be crash-safe: a holder that dies without releasing must not
    wedge the resource forever (a Postgres session lock is released when
    the connection drops; the in-memory lock is forgotten on restart and
    re-derived from the audit log + idempotency key).
    """

    distributed: bool

    def acquire(self, resource_id: str) -> AbstractAsyncContextManager[None]:
        """Return an async context manager holding the per-resource lock."""
        ...


def _validate_common(receipt: ResourceLockAcquisitionReceipt) -> None:
    text_fields = (
        receipt.provider_id,
        receipt.provider_version,
        receipt.producer_id,
        receipt.producer_version,
        receipt.trust_anchor_id,
    )
    if not all(type(value) is str and value.strip() and len(value) <= 512 for value in text_fields):
        raise ValueError("resource lock receipt identity fields MUST be bounded")
    _validate_resource_lock_key(receipt.lock_key)
    for digest in (
        receipt.target_digest,
        receipt.action_digest,
        receipt.owner_token_digest,
        receipt.provider_attestation_digest,
        receipt.request_digest,
        receipt.receipt_digest,
    ):
        if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
            raise ValueError("resource lock receipt digest fields MUST be SHA-256")
    if (
        type(receipt.source_revision) is not str
        or _REVISION.fullmatch(receipt.source_revision) is None
    ):
        raise ValueError("resource lock receipt source revision MUST be canonical")
    _validate_utc("acquired_at", receipt.acquired_at)
    if receipt.valid_until is not None:
        _validate_utc("valid_until", receipt.valid_until)


def _validate_request_receipt_binding(
    request: ResourceLockAcquisitionRequest,
    receipt: ResourceLockAcquisitionReceipt,
) -> None:
    if (
        receipt.request_digest != request.request_digest
        or receipt.lock_key != request.lock_key
        or receipt.target_digest != request.target_digest
        or receipt.action_digest != request.action_digest
        or receipt.attempt != request.attempt
        or receipt.producer_id != request.producer_id
        or receipt.producer_version != request.producer_version
        or receipt.source_revision != request.source_revision
    ):
        raise ValueError("resource lock receipt does not match its acquisition request")


def _utc(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"resource lock {name} MUST include a timezone")
    return value.astimezone(UTC)


def _validate_text(name: str, value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError(f"resource lock {name} MUST be bounded")


def _validate_resource_lock_key(lock_key: str) -> None:
    if type(lock_key) is not str or not lock_key:
        raise ValueError("resource lock lock key MUST be non-empty")
    prefix = "fdai:resource:"
    if lock_key != lock_key.strip() or not lock_key.startswith(prefix):
        raise ValueError("resource lock lock key MUST be canonical")
    _validate_target_ref(lock_key.removeprefix(prefix))


def _validate_target_ref(target_ref: str) -> None:
    if type(target_ref) is not str or not target_ref.strip() or target_ref != target_ref.strip():
        raise ValueError("resource lock target reference MUST be canonical")


def _validate_utc(name: str, value: datetime) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"resource lock {name} MUST include a timezone")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"resource lock {name} MUST be normalized to UTC")


def _payload_digest(payload: Mapping[str, object], domain: str) -> str:
    body = dict(payload)
    if domain == "resource-lock-request":
        body.pop("request_digest", None)
    body.pop("receipt_digest", None)
    body.pop("assessment_digest", None)
    return content_digest({"domain": domain, "body": _normalize_digest_value(body)})


def _normalize_digest_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(
        value,
        (
            ResourceLockAcquisitionRequest,
            ResourceLockAcquisitionReceipt,
            LiveLockOwnershipAssessment,
            ResourceLockReleaseReceipt,
        ),
    ):
        return _normalize_digest_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _normalize_digest_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_digest_value(item) for item in value]
    return value


def _content_digest(
    value: (
        ResourceLockAcquisitionRequest
        | ResourceLockAcquisitionReceipt
        | LiveLockOwnershipAssessment
        | ResourceLockReleaseReceipt
    ),
    domain: str,
) -> str:
    return _payload_digest(asdict(value), domain)


__all__ = [
    "EvidenceResourceLock",
    "HeldResourceLock",
    "HeldResourceLockLifecycle",
    "LiveLockOwnershipAssessment",
    "LockOwnershipRejectionReason",
    "MAX_LOCK_ASSESSMENT_TTL",
    "ResourceLock",
    "ResourceLockAcquisitionRequest",
    "ResourceLockAcquisitionReceipt",
    "ResourceLockReleaseReceipt",
    "ResourceLockReleaseState",
    "require_evidence_resource_lock",
    "require_current_lock_ownership",
    "resource_lock_key",
    "resource_lock_target_digest",
]
