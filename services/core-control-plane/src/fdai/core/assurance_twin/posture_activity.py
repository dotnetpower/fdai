"""Assurance Twin - bounded read-only posture/review activity value objects.

Turns an already-computed :class:`~fdai.core.assurance_twin.report.PostureAssessmentReport`
or ambient :class:`~fdai.shared.providers.iac_review.IacReview` into one
:class:`~fdai_service_contracts.AgentOperationalActivity` record - the existing
bounded, authority-free evidence channel Heimdall already uses for other
observation domains (``resource-health``, ``metrics``, ``cost``, ...).

The activity is a bounded **tip value**, not the authoritative report body.
The delivery recorder stages tips in the durable ledger's transactional outbox.
The value is returned to the caller for audit/logging use, and the
durable finding-level content is always written separately by
``fdai.delivery.assurance_twin_posture`` so this module stays pure and CSP
neutral, matching every other ``core/assurance_twin/`` component
([module placement](../../../../../docs/roadmap/operations/assurance-twin.md#module-placement)).

Design invariants
------------------

- **Pure**: no I/O, no clock reads beyond the values already carried by the
  report/review the caller computed.
- **Bounded**: ``evidence_count`` mirrors the finding count; the record never
  carries a resource identifier, finding text, or customer value.
- **No authority**: ``execution_authority`` stays the schema ``const`` of
  ``False``. The twin never grants approval or execution through this
  channel
  ([safety posture](../../../../../docs/roadmap/operations/assurance-twin.md#safety-posture)).
- **Fail-closed status**: a ``stale`` or ``unavailable`` freshness MUST carry
  at least one reason code, matching the shared contract's requirement that
  a degraded/failed activity explain itself.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from fdai_service_contracts import (
    AgentOperationalActivity,
    OperationalActivityKind,
    OperationalActivityStatus,
    OperationalFreshness,
)
from pydantic import BaseModel, ConfigDict, Field

from fdai.core.assurance_twin.report import PostureAssessmentReport
from fdai.shared.providers.iac_review import IacReview

_POSTURE_OWNER: Literal["Heimdall"] = "Heimdall"
_REVIEW_OWNER: Literal["Forseti"] = "Forseti"
_PRODUCER: Literal["assurance-twin"] = "assurance-twin"
_POSTURE_SOURCE = "assurance-twin:posture"
_REVIEW_SOURCE: Literal["assurance-twin:review"] = "assurance-twin:review"


class AssuranceTwinReviewActivity(BaseModel):
    """Private, authority-free Forseti event; the shared stage kind is observer-only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    activity_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)
    kind: Literal["assurance_twin_review"] = "assurance_twin_review"
    status: OperationalActivityStatus
    owner_agent: Literal["Forseti"] = "Forseti"
    producer: Literal["assurance-twin"] = "assurance-twin"
    observed_at: datetime
    source: Literal["assurance-twin:review"] = "assurance-twin:review"
    freshness: OperationalFreshness
    evidence_count: int = Field(ge=0, le=200)
    correlation_id: str = Field(min_length=1, max_length=256)
    reason_codes: tuple[str, ...] = ()
    execution_authority: Literal[False] = False


def build_posture_report_activity(
    report: PostureAssessmentReport,
    *,
    correlation_id: str,
    freshness: OperationalFreshness,
    reason_codes: tuple[str, ...] = (),
    superseded: bool = False,
) -> AgentOperationalActivity:
    """Build one bounded activity tip for an on-demand posture report.

    Raises:
        ValueError: when ``correlation_id`` is empty or ``freshness`` is
            ``stale``/``unavailable`` without a reason code.
    """

    if not correlation_id.strip():
        raise ValueError("posture report activity correlation_id MUST be non-empty")
    status = (
        OperationalActivityStatus.SUPERSEDED if superseded else _status_for(freshness, reason_codes)
    )
    report_identity = _posture_evidence_identity(report, freshness, reason_codes)
    correlation_identity = _privacy_safe_identity(correlation_id)
    return AgentOperationalActivity(
        schema_version="1.2.0",
        activity_id=f"assurance-twin.posture-report:{report_identity}:{status.value}",
        idempotency_key=f"assurance-twin.posture-report:{report_identity}:{status.value}",
        kind=OperationalActivityKind.ASSURANCE_TWIN_POSTURE,
        status=status,
        owner_agent=_POSTURE_OWNER,
        producer=_PRODUCER,
        observed_at=_parse_timestamp(report.generated_at),
        source=_POSTURE_SOURCE,
        freshness=freshness,
        evidence_count=len(report.findings),
        correlation_id=correlation_identity,
        reason_codes=reason_codes,
    )


def build_change_review_activity(
    review: IacReview,
    *,
    correlation_id: str,
    freshness: OperationalFreshness,
    reason_codes: tuple[str, ...] = (),
) -> AssuranceTwinReviewActivity:
    """Build one bounded activity tip for an ambient per-change review.

    Raises:
        ValueError: when ``correlation_id`` is empty or ``freshness`` is
            ``stale``/``unavailable`` without a reason code.
    """

    if not correlation_id.strip():
        raise ValueError("change review activity correlation_id MUST be non-empty")
    status = _status_for(freshness, reason_codes)
    review_identity = _privacy_safe_identity(review.review_key)
    correlation_identity = _privacy_safe_identity(correlation_id)
    return AssuranceTwinReviewActivity(
        activity_id=f"assurance-twin.change-review:{review_identity}:{status.value}",
        idempotency_key=f"assurance-twin.change-review:{review_identity}:{status.value}",
        status=status,
        owner_agent=_REVIEW_OWNER,
        producer=_PRODUCER,
        observed_at=_parse_timestamp(review.generated_at),
        source=_REVIEW_SOURCE,
        freshness=freshness,
        evidence_count=len(review.findings),
        correlation_id=correlation_identity,
        reason_codes=reason_codes,
    )


def _status_for(
    freshness: OperationalFreshness,
    reason_codes: tuple[str, ...],
) -> OperationalActivityStatus:
    """Derive the activity status from freshness, never from a guess.

    A stale or unavailable observation MUST cite a reason so the shared
    contract's fail-closed invariant (degraded/failed activity MUST include
    a reason code) is satisfied by construction.
    """

    if freshness is OperationalFreshness.UNAVAILABLE:
        if not reason_codes:
            raise ValueError("unavailable assurance-twin activity MUST include a reason code")
        return OperationalActivityStatus.FAILED
    if freshness is OperationalFreshness.STALE:
        if not reason_codes:
            raise ValueError("stale assurance-twin activity MUST include a reason code")
        return OperationalActivityStatus.DEGRADED
    if freshness is OperationalFreshness.UNKNOWN:
        raise ValueError("unknown assurance-twin evidence cannot claim completion")
    return OperationalActivityStatus.COMPLETED


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("assurance-twin activity timestamp MUST include a timezone")
    return parsed


def _posture_evidence_identity(
    report: PostureAssessmentReport,
    freshness: OperationalFreshness,
    reason_codes: tuple[str, ...],
) -> str:
    body = {
        **report.to_dict(),
        "generated_at": _parse_timestamp(report.generated_at).astimezone(UTC).isoformat(),
        "freshness": freshness.value,
        "reason_codes": list(reason_codes),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return _privacy_safe_identity(encoded)


def _privacy_safe_identity(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


__all__ = [
    "AssuranceTwinReviewActivity",
    "build_change_review_activity",
    "build_posture_report_activity",
]
