"""Read-only recognition of unreleased alert-noise 1.0.0 durable records.

Alert-noise plan and result contracts 1.0.0 carried the retired manual-PR execution path and never
appeared in a release. Such records can remain only in manually configured environments. This module
authenticates them exactly, so each durable reader can retire them explicitly instead of failing.
It returns identity summaries only, never an archived model, and it is bound to no codec. It cannot
make a retired plan or result current, executable, or publishable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeGuard, TypeVar

from pydantic import BaseModel

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseCommand,
    AlertNoiseResult,
    SignedAlertResult,
    verify_alert_record,
)

LEGACY_ALERT_CONTRACT_VERSION = "1.0.0"
LEGACY_ALERT_CONTRACT_REASON = "legacy_contract_retired"

_Model = TypeVar("_Model", bound=BaseModel)


# Archived shapes keep the original contract docstrings, so their schemas equal the preserved
# 1.0.0 files and their canonical bytes match the retired producer.
class _AlertChangePlanV100(AlertChangePlan):
    __doc__ = AlertChangePlan.__doc__

    schema_version: Literal["1.0.0"] = "1.0.0"  # type: ignore[assignment]
    execution_path: Literal["pr_manual"] = "pr_manual"  # type: ignore[assignment]


class _AlertNoiseResultV100(AlertNoiseResult):
    __doc__ = AlertNoiseResult.__doc__

    schema_version: Literal["1.0.0"] = "1.0.0"  # type: ignore[assignment]
    plan: _AlertChangePlanV100 | None = None


class _SignedAlertResultV100(SignedAlertResult):
    __doc__ = SignedAlertResult.__doc__

    result: _AlertNoiseResultV100


@dataclass(frozen=True, slots=True)
class LegacyAlertPlan:
    """Authenticated identity of one retired plan; never a plan contract."""

    digest: str


@dataclass(frozen=True, slots=True)
class LegacyAlertResult:
    """Authenticated identity of one retired result; never a result contract."""

    command: AlertNoiseCommand
    record_digest: str
    recorded_at: datetime


def _candidate(raw: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(raw, Mapping) and raw.get("schema_version") == LEGACY_ALERT_CONTRACT_VERSION


def _exact(model: type[_Model], raw: Mapping[str, object]) -> _Model:
    try:
        record = model.model_validate(dict(raw))
        canonical = record.model_dump(mode="json") == dict(raw)
    except (TypeError, ValueError):
        # Validation text can echo private request content; report only the category.
        raise ValueError("legacy alert record is invalid") from None
    if not canonical:
        raise ValueError("legacy alert record is not canonical")
    return record


def _summary(result: _AlertNoiseResultV100) -> LegacyAlertResult:
    return LegacyAlertResult(
        command=result.command,
        record_digest=digest_record(result),
        recorded_at=result.recorded_at,
    )


def decode_legacy_alert_plan(raw: object, *, expected_digest: str) -> LegacyAlertPlan | None:
    """Return a retired plan identity, ``None`` for other versions, or raise when invalid."""
    if not _candidate(raw):
        return None
    digest = digest_record(_exact(_AlertChangePlanV100, raw))
    if digest != expected_digest:
        raise ValueError("legacy alert plan digest does not match its record")
    return LegacyAlertPlan(digest=digest)


def decode_legacy_alert_result(raw: object) -> LegacyAlertResult | None:
    """Return a retained retired-result identity, ``None`` for other versions, or raise."""
    if not _candidate(raw):
        return None
    return _summary(_exact(_AlertNoiseResultV100, raw))


def decode_legacy_signed_alert_result(raw: object, *, key: bytes) -> LegacyAlertResult | None:
    """Authenticate a retained signed retired result before any reader relies on it."""
    if not isinstance(raw, Mapping) or not _candidate(raw.get("result")):
        return None
    signed = _exact(_SignedAlertResultV100, raw)
    verify_alert_record(signed.result, signed.signature, key)
    return _summary(signed.result)


__all__ = [
    "LEGACY_ALERT_CONTRACT_REASON",
    "LEGACY_ALERT_CONTRACT_VERSION",
    "LegacyAlertPlan",
    "LegacyAlertResult",
    "decode_legacy_alert_plan",
    "decode_legacy_alert_result",
    "decode_legacy_signed_alert_result",
]
