"""Durable, scope-owned alert-quality preferences and no-authority projections.

Responsibility: retain enabled preferences with immutable revision audits.
Boundary: HTTP owns current human Owner checks; preferences never alter promotion.
Authority and state: one Operator state_kv record is both the CAS index and audit.
Dependencies: durable read/create/find primitives and a synchronous pre-insert guard.
Deployment: the existing Operator service owns the store; no fallback is created.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol, Self

from fdai_service_contracts.alert_noise import Ref, digest_record
from fdai_service_contracts.alert_noise_base import AlertContractBase, AlertTime, FalseOnly
from fdai_service_contracts.executor_models import Digest
from pydantic import ConfigDict, Field, StrictBool, model_validator

from fdai_operator_service.alert_quality_records import (
    AlertQualityStateStore,
    AlertQualityUnavailableError,
    validate_alert_quality_scope,
)

ALERT_QUALITY_PREFERENCE_PREFIX = "operator-alert-quality-preference:"
MAX_ALERT_QUALITY_REVISION = 9_007_199_254_740_991
_MAX_ADVANCES = 8
_MAX_RECORD_BYTES = 4096
Revision = Annotated[int, Field(strict=True, ge=0, le=MAX_ALERT_QUALITY_REVISION)]
ExpectedRevision = Annotated[int, Field(strict=True, ge=0, lt=MAX_ALERT_QUALITY_REVISION)]
SettingsUnavailableReason = Literal[
    "preference_store_unavailable",
    "source_unavailable",
    "writer_unavailable",
    "producer_not_ready",
]


class AlertQualityPreferenceConflictError(RuntimeError):
    """A scoped preference revision changed; no replacement or automatic retry is allowed."""


class AlertQualityPreference(AlertContractBase):
    """One append-only preference change, including its opaque actor and predecessor."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=False)

    kind: Literal["operator.alert-quality.preference"] = "operator.alert-quality.preference"
    scope_ref: Ref
    revision: Annotated[int, Field(strict=True, ge=1, le=MAX_ALERT_QUALITY_REVISION)]
    expected_revision: ExpectedRevision
    previous_digest: Digest | None
    enabled: StrictBool
    recorded_at: AlertTime
    requester_ref: Annotated[str, Field(pattern=r"^principal:[a-f0-9]{64}$")]
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def exact_revision(self) -> Self:
        validate_alert_quality_scope(self.scope_ref)
        if self.revision != self.expected_revision + 1 or (
            (self.expected_revision == 0) != (self.previous_digest is None)
        ):
            raise ValueError("alert quality preference predecessor is invalid")
        if re.fullmatch(r"principal:[a-f0-9]{64}", self.requester_ref) is None:
            raise ValueError("alert quality preference requester MUST be opaque")
        return self


class AlertQualityPreferenceStore(Protocol):
    """Scope-owned preferences shared by authorized readers, not per-user authority.

    None from read means an explicit unsaved default, not a storage failure. Writers
    MUST fence the expected revision durably and call before_commit synchronously
    after their reads and immediately before invoking the atomic insert. Exceptions never
    authorize a fallback, and disabling does not cancel previously accepted work.
    """

    async def read(self, *, scope_ref: str) -> AlertQualityPreference | None: ...

    async def set_enabled(
        self,
        *,
        scope_ref: str,
        enabled: bool,
        expected_revision: int,
        requester_ref: str,
        before_commit: Callable[[], None],
    ) -> AlertQualityPreference: ...


class AlertQualitySettingsBody(AlertContractBase):
    """Accept only an explicit scope, strict preference and optional body revision.

    HTTP requires exactly one concurrency source: expected_revision or If-Match.
    An explicit null revision is not an omitted precondition.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=False)

    scope_ref: Ref
    enabled: StrictBool
    expected_revision: ExpectedRevision | None = None

    @model_validator(mode="after")
    def exact_scope_and_revision(self) -> Self:
        validate_alert_quality_scope(self.scope_ref)
        if "expected_revision" in self.model_fields_set and self.expected_revision is None:
            raise ValueError("expected_revision MUST be an integer")
        return self


class AlertQualityPrerequisites(AlertContractBase):
    """Binding/readiness facts only; none is approval, promotion or execution authority."""

    source_bound: StrictBool
    writer_bound: StrictBool
    producer_ready: StrictBool
    preference_store_available: StrictBool

    @property
    def available(self) -> bool:
        """Report request capability prerequisites independently of the enabled preference."""
        return self.unavailable_reason is None

    @property
    def unavailable_reason(self) -> SettingsUnavailableReason | None:
        """Return the first missing prerequisite without exposing dependency details."""
        if not self.preference_store_available:
            return "preference_store_unavailable"
        if not self.source_bound:
            return "source_unavailable"
        if not self.writer_bound:
            return "writer_unavailable"
        return None if self.producer_ready else "producer_not_ready"


class AlertQualitySettingsResponse(AlertContractBase):
    """Sanitized settings; an unsaved default has no fabricated timestamp or actor."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=False)

    source: Literal["alert-noise-governance"] = "alert-noise-governance"
    scope_ref: Ref
    available: StrictBool
    enabled: StrictBool | None
    mode: Literal["shadow"] = "shadow"
    execution_authority: FalseOnly = False
    prerequisites: AlertQualityPrerequisites
    unavailable_reason: SettingsUnavailableReason | None
    preference_state: Literal["default", "recorded", "unavailable"]
    revision: Revision | None
    recorded_at: AlertTime | None

    @model_validator(mode="after")
    def explicit_state(self) -> Self:
        validate_alert_quality_scope(self.scope_ref)
        if self.available != self.prerequisites.available or (
            self.unavailable_reason != self.prerequisites.unavailable_reason
        ):
            raise ValueError("alert quality settings availability is inconsistent")
        if self.preference_state == "unavailable":
            if any(value is not None for value in (self.enabled, self.revision, self.recorded_at)):
                raise ValueError("unavailable preferences MUST NOT invent current state")
        elif self.enabled is None or self.revision is None:
            raise ValueError("readable preferences require an enabled value and revision")
        elif self.preference_state == "default":
            if self.revision != 0 or self.recorded_at is not None:
                raise ValueError("unsaved defaults MUST NOT claim a durable revision or time")
        elif self.revision == 0 or self.recorded_at is None:
            raise ValueError("recorded preferences require a durable revision and time")
        if self.prerequisites.preference_store_available != (
            self.preference_state != "unavailable"
        ):
            raise ValueError("alert quality preference availability is inconsistent")
        return self


def project_alert_quality_settings(
    *,
    scope_ref: str,
    preference: AlertQualityPreference | None,
    prerequisites: AlertQualityPrerequisites,
    default_enabled: bool = True,
) -> AlertQualitySettingsResponse:
    """Project readable preference state separately from missing capability prerequisites."""
    if type(default_enabled) is not bool:
        raise ValueError("alert quality default preference MUST be a boolean")
    if preference is not None and preference.scope_ref != scope_ref:
        raise AlertQualityUnavailableError("alert quality preference binding is unavailable")
    readable = prerequisites.preference_store_available
    enabled = default_enabled if preference is None else preference.enabled
    return AlertQualitySettingsResponse(
        scope_ref=scope_ref,
        available=prerequisites.available,
        enabled=enabled if readable else None,
        prerequisites=prerequisites,
        unavailable_reason=prerequisites.unavailable_reason,
        preference_state=(
            "unavailable" if not readable else "default" if preference is None else "recorded"
        ),
        revision=(0 if preference is None else preference.revision) if readable else None,
        recorded_at=preference.recorded_at if readable and preference is not None else None,
    )


def verify_alert_quality_preference(
    preference: AlertQualityPreference, *, scope_ref: str, now: datetime
) -> AlertQualityPreference:
    """Recheck injected records and reject another scope, future state or coercion."""
    checked = _decode(preference.model_dump(mode="json"))
    if checked.scope_ref != scope_ref or checked.recorded_at > _aware(now):
        raise AlertQualityUnavailableError("alert quality preference binding is unavailable")
    return checked


class StateKvAlertQualityPreferenceStore:
    """Append one immutable CAS/audit record using the existing Operator state primitives.

    The scope namespace is independent of the requester: two scoped Owners compete
    for the same revision. A failed insert is a conflict even for an identical value.
    find_state is only a hint; exact records and bounded successor reads establish
    the head. No process-local cache, SQL, overwrite, retry loop or external call exists.
    """

    def __init__(
        self,
        store: AlertQualityStateStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store, self._clock = store, clock

    async def read(self, *, scope_ref: str) -> AlertQualityPreference | None:
        """Read the narrow scope head; missing state is distinct from an invalid history."""
        head = await self._head(scope_ref)
        if head is None:
            return None
        return verify_alert_quality_preference(head, scope_ref=scope_ref, now=self._clock())

    async def set_enabled(
        self,
        *,
        scope_ref: str,
        enabled: bool,
        expected_revision: int,
        requester_ref: str,
        before_commit: Callable[[], None],
    ) -> AlertQualityPreference:
        """Commit a revision-bound preference and actor together, or raise without replacement."""
        command = AlertQualitySettingsBody(
            scope_ref=scope_ref, enabled=enabled, expected_revision=expected_revision
        )
        head = await self.read(scope_ref=scope_ref)
        if expected_revision != (0 if head is None else head.revision):
            raise AlertQualityPreferenceConflictError("alert quality preference revision conflict")
        record = AlertQualityPreference(
            scope_ref=scope_ref,
            enabled=command.enabled,
            revision=expected_revision + 1,
            expected_revision=expected_revision,
            previous_digest=None if head is None else digest_record(head),
            recorded_at=_aware(self._clock()),
            requester_ref=requester_ref,
        )
        if head is not None:
            _verify_successor(head, record)
        key, value = _key(scope_ref, record.revision), record.model_dump(mode="json")
        before_commit()
        inserted = await self._store.create_state(key, value)
        if inserted is False:
            raise AlertQualityPreferenceConflictError("alert quality preference revision conflict")
        if inserted is not True:
            raise AlertQualityUnavailableError(
                "alert quality preference persistence is unavailable"
            )
        persisted = await self._store.read_state(key)
        if persisted is None or _decode(persisted) != record:
            raise AlertQualityUnavailableError("alert quality preference readback is unavailable")
        return record

    async def _head(self, scope_ref: str) -> AlertQualityPreference | None:
        prefix = _prefix(scope_ref)
        raw = await self._store.find_state(
            prefix=prefix, field="kind", value="operator.alert-quality.preference"
        )
        if raw is None:
            if await self._store.read_state(_key(scope_ref, 1)) is not None:
                raise AlertQualityUnavailableError("alert quality preference index is unavailable")
            return None
        head = _decode(raw)
        exact = await self._store.read_state(_key(scope_ref, head.revision))
        if head.scope_ref != scope_ref or exact is None or _decode(exact) != head:
            raise AlertQualityUnavailableError(
                "alert quality preference index binding is unavailable"
            )
        if head.revision > 1:
            previous = await self._store.read_state(_key(scope_ref, head.revision - 1))
            if previous is None:
                raise AlertQualityUnavailableError(
                    "alert quality preference predecessor is unavailable"
                )
            _verify_successor(_decode(previous), head)
        for _ in range(_MAX_ADVANCES):
            successor = await self._store.read_state(_key(scope_ref, head.revision + 1))
            if successor is None:
                return head
            current = _decode(successor)
            _verify_successor(head, current)
            head = current
        raise AlertQualityUnavailableError("alert quality preference history is busy")


def _prefix(scope_ref: str) -> str:
    validate_alert_quality_scope(scope_ref)
    raw = json.dumps(["operator-alert-quality-preference-v1", scope_ref], separators=(",", ":"))
    return f"{ALERT_QUALITY_PREFERENCE_PREFIX}{hashlib.sha256(raw.encode()).hexdigest()}:index:"


def _key(scope_ref: str, revision: int) -> str:
    return f"{_prefix(scope_ref)}{revision:020d}"


def _decode(value: Mapping[str, object]) -> AlertQualityPreference:
    try:
        raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(raw.encode()) > _MAX_RECORD_BYTES:
            raise ValueError("preference exceeds its byte bound")
        record = AlertQualityPreference.model_validate_json(raw, strict=True)
        if json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) != raw:
            raise ValueError("preference roundtrip failed")
        return record
    except (TypeError, ValueError, RecursionError) as exc:
        raise AlertQualityUnavailableError("alert quality preference is unavailable") from exc


def _verify_successor(previous: AlertQualityPreference, current: AlertQualityPreference) -> None:
    if (
        current.scope_ref != previous.scope_ref
        or current.expected_revision != previous.revision
        or current.previous_digest != digest_record(previous)
        or current.recorded_at < previous.recorded_at
    ):
        raise AlertQualityUnavailableError("alert quality preference history is inconsistent")


def _aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise AlertQualityUnavailableError("alert quality preference clock is unavailable")
    return now
