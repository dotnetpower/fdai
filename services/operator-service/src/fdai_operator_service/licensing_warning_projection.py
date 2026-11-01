"""Authenticated, secret-free Operator licensing status and renewal warning projection."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Literal

from fdai_service_contracts import ContractBase
from pydantic import Field, field_validator, model_validator

DEFAULT_RENEWAL_WARNING_WINDOW: Final = timedelta(days=7)
MAX_OBSERVATION_STALENESS: Final = timedelta(minutes=5)
_SAFE_IDENTIFIER: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SECRET_TOKEN_PATTERN: Final = re.compile(
    r"(-----BEGIN|PRIVATE KEY|eyJ[A-Za-z0-9_-]{10,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{24,})",
    re.IGNORECASE,
)
_FORBIDDEN_INPUT_KEYS: Final = frozenset(
    {
        "token",
        "raw_token",
        "license_token",
        "private_key",
        "signing_key",
        "signature",
        "document_bytes",
    }
)


class LicensingWarningState(StrEnum):
    """Closed Operator status and proactive renewal warning states."""

    NORMAL = "normal"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    CLOCK_REGRESSION = "clock_regression"
    READ_ONLY_TRIAL = "read_only_trial"


WatermarkNoticeLiteral = Literal["none", "evaluation-ended", "not-activated"]


class LicensingWarningProjection(ContractBase):
    """Authenticated, secret-free licensing status and renewal warning projection."""

    type: Literal["licensing.warning-projection"] = "licensing.warning-projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    read_only: Literal[True] = True
    authority: Literal["none"] = "none"
    secret_free: Literal[True] = True
    principal_id: str = Field(min_length=1, max_length=512)
    state: LicensingWarningState
    license_status: str = Field(min_length=1, max_length=64)
    watermark_notice: WatermarkNoticeLiteral
    acting_available: bool
    proactive_warning: bool
    license_id: str | None = Field(default=None, max_length=128)
    expires_at: datetime | None = None
    remaining_seconds: int | None = Field(default=None, ge=0)
    remaining_days: int | None = Field(default=None, ge=0)
    observed_at: datetime
    reason_code: str = Field(min_length=1, max_length=128)

    @field_validator("observed_at", "expires_at")
    @classmethod
    def _validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("licensing projection timestamps MUST be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("license_id", "reason_code", "license_status")
    @classmethod
    def _reject_secret_like_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _SECRET_TOKEN_PATTERN.search(value) or _SAFE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError("licensing warning projection MUST NOT carry token or key material")
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> LicensingWarningProjection:
        if self.state in {
            LicensingWarningState.EXPIRED,
            LicensingWarningState.CLOCK_REGRESSION,
            LicensingWarningState.READ_ONLY_TRIAL,
        }:
            if self.acting_available:
                raise ValueError("degraded licensing state cannot report acting_available=True")
            if not self.proactive_warning:
                raise ValueError("degraded licensing state MUST set proactive_warning=True")
            if self.watermark_notice == "none":
                raise ValueError("degraded licensing state MUST carry an active watermark notice")
        if self.state is LicensingWarningState.EXPIRING_SOON and not self.proactive_warning:
            raise ValueError("expiring_soon state MUST set proactive_warning=True")
        return self


def build_licensing_warning_projection(
    *,
    principal_id: str | None,
    license_status: str,
    acting_available: bool,
    observed_at: datetime | None,
    now: datetime | None = None,
    license_id: str | None = None,
    expires_at: datetime | None = None,
    clock_blocked: bool = False,
    reason_code: str | None = None,
    warning_window: timedelta = DEFAULT_RENEWAL_WARNING_WINDOW,
    raw_metadata: dict[str, object] | None = None,
) -> LicensingWarningProjection:
    """Build a secret-free Operator licensing warning projection at ``now``."""
    if principal_id is None or not principal_id.strip():
        raise PermissionError("licensing warning projection requires an authenticated principal")
    if raw_metadata is not None and (_FORBIDDEN_INPUT_KEYS & set(raw_metadata)):
        raise ValueError("licensing warning projection input MUST NOT include secret or token keys")
    current_now = (now or datetime.now(UTC)).astimezone(UTC)
    if current_now.tzinfo is None or current_now.utcoffset() is None:
        raise ValueError("current_now MUST be timezone-aware")
    if warning_window <= timedelta(0):
        raise ValueError("warning_window MUST be positive")

    safe_license_id = _sanitize_identifier(license_id)
    if observed_at is None or observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return LicensingWarningProjection(
            principal_id=principal_id.strip(),
            state=LicensingWarningState.READ_ONLY_TRIAL,
            license_status="absent",
            watermark_notice="not-activated",
            acting_available=False,
            proactive_warning=True,
            license_id=None,
            expires_at=None,
            remaining_seconds=None,
            remaining_days=None,
            observed_at=current_now,
            reason_code="entitlement_state_missing",
        )

    obs_utc = observed_at.astimezone(UTC)
    exp_utc = expires_at.astimezone(UTC) if expires_at is not None else None
    if abs(current_now - obs_utc) > MAX_OBSERVATION_STALENESS:
        return LicensingWarningProjection(
            principal_id=principal_id.strip(),
            state=LicensingWarningState.READ_ONLY_TRIAL,
            license_status="stale",
            watermark_notice="not-activated",
            acting_available=False,
            proactive_warning=True,
            license_id=safe_license_id,
            expires_at=exp_utc,
            remaining_seconds=None,
            remaining_days=None,
            observed_at=obs_utc,
            reason_code="entitlement_state_stale",
        )

    if clock_blocked or license_status == "clock_regression" or reason_code == "clock_regression":
        return LicensingWarningProjection(
            principal_id=principal_id.strip(),
            state=LicensingWarningState.CLOCK_REGRESSION,
            license_status="clock_regression",
            watermark_notice="not-activated",
            acting_available=False,
            proactive_warning=True,
            license_id=safe_license_id,
            expires_at=exp_utc,
            remaining_seconds=0 if exp_utc is not None else None,
            remaining_days=0 if exp_utc is not None else None,
            observed_at=obs_utc,
            reason_code="clock_regression_detected",
        )

    if license_status == "expired" or (exp_utc is not None and current_now >= exp_utc):
        return LicensingWarningProjection(
            principal_id=principal_id.strip(),
            state=LicensingWarningState.EXPIRED,
            license_status="expired",
            watermark_notice="evaluation-ended",
            acting_available=False,
            proactive_warning=True,
            license_id=safe_license_id,
            expires_at=exp_utc,
            remaining_seconds=0,
            remaining_days=0,
            observed_at=obs_utc,
            reason_code=_sanitize_identifier(reason_code) or "entitlement_expired",
        )

    if not acting_available or license_status not in {"active", "issuer-workstation"}:
        return LicensingWarningProjection(
            principal_id=principal_id.strip(),
            state=LicensingWarningState.READ_ONLY_TRIAL,
            license_status=_sanitize_identifier(license_status) or "absent",
            watermark_notice="not-activated",
            acting_available=False,
            proactive_warning=True,
            license_id=safe_license_id,
            expires_at=exp_utc,
            remaining_seconds=None,
            remaining_days=None,
            observed_at=obs_utc,
            reason_code=_sanitize_identifier(reason_code) or "read_only_unactivated",
        )

    rem_seconds: int | None = None
    rem_days: int | None = None
    if exp_utc is not None:
        delta = exp_utc - current_now
        rem_seconds = max(0, int(delta.total_seconds()))
        rem_days = max(0, math.ceil(rem_seconds / 86400))
        if delta <= warning_window:
            return LicensingWarningProjection(
                principal_id=principal_id.strip(),
                state=LicensingWarningState.EXPIRING_SOON,
                license_status=_sanitize_identifier(license_status) or "active",
                watermark_notice="none",
                acting_available=True,
                proactive_warning=True,
                license_id=safe_license_id,
                expires_at=exp_utc,
                remaining_seconds=rem_seconds,
                remaining_days=rem_days,
                observed_at=obs_utc,
                reason_code=_sanitize_identifier(reason_code) or "renewal_window_approaching",
            )

    return LicensingWarningProjection(
        principal_id=principal_id.strip(),
        state=LicensingWarningState.NORMAL,
        license_status=_sanitize_identifier(license_status) or "active",
        watermark_notice="none",
        acting_available=True,
        proactive_warning=False,
        license_id=safe_license_id,
        expires_at=exp_utc,
        remaining_seconds=rem_seconds,
        remaining_days=rem_days,
        observed_at=obs_utc,
        reason_code=_sanitize_identifier(reason_code) or "entitlement_active",
    )


def _sanitize_identifier(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if _SECRET_TOKEN_PATTERN.search(cleaned) or _SAFE_IDENTIFIER.fullmatch(cleaned) is None:
        raise ValueError("licensing identifier contains forbidden or secret-like characters")
    return cleaned


__all__ = [
    "DEFAULT_RENEWAL_WARNING_WINDOW",
    "LicensingWarningProjection",
    "LicensingWarningState",
    "MAX_OBSERVATION_STALENESS",
    "build_licensing_warning_projection",
]
