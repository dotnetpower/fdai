"""Read-only, per-resource and signal Finding state, independent of tick retention."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FindingSeverity = Literal["critical", "high", "medium", "low"]
FINDING_STATE_PREFIX = "runtime:analyzer-finding-current:"
_NON_FAULT_SIGNALS = frozenset(
    {
        "insufficient_evidence",
        "conflicting_evidence",
        "stale_evidence",
        "rollout_replacement",
    }
)
_FAULT_ASSESSMENTS = {
    "host_cpu": frozenset({"cpu_threshold_observed"}),
    "resource_availability": frozenset(
        {
            "stop_observed",
            "expected_running_not_observed",
            "expected_stop_not_observed",
        }
    ),
}


def is_operational_finding(signal: str, assessment_status: str | None) -> bool:
    """Classify canonical detector tokens, never free-form observation text."""
    if signal in _NON_FAULT_SIGNALS:
        return False
    statuses = _FAULT_ASSESSMENTS.get(signal)
    return statuses is None or assessment_status is None or assessment_status in statuses


def finding_identity(resource_kind: str, resource_ref: str, signal: str) -> str:
    value = json.dumps([resource_kind, resource_ref, signal], separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


class FindingState(BaseModel):
    """A derived unresolved/resolved record, never Incident or execution authority."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True, validate_default=True
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    finding_id: str
    revision: int = Field(ge=1)
    notification_version: int = Field(ge=1)
    notification_reason: Literal["opened", "escalated", "recovered"]
    notification_changed_at: datetime
    resource_ref: str
    resource_kind: str
    signal: str
    severity: FindingSeverity
    status: Literal["active", "resolved"]
    observation: str
    observation_key: str
    observation_digest: str
    first_seen_at: datetime
    occurred_at: datetime
    recorded_at: datetime
    current_state: str
    evidence_complete: bool
    evidence_state: str
    recovery_closed: bool | None
    assessed_by: str | None
    evidence_refs: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    publication: str
    cause_claim_supported: Literal[False] = False
    execution_authority: Literal[False] = False
