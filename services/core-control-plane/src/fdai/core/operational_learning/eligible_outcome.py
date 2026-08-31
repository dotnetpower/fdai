"""Compose one immutable operational case from an eligible terminal outcome."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.core.case_history import (
    FailureFingerprint,
    OperationalCaseInput,
    OperationalEvidenceSourceKind,
    OperationalOutcomeClass,
    OperationalReceiptFact,
    OperationalReceiptType,
)
from fdai.core.case_history.models import CaseKind

_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PinnedLearningRelease:
    """One immutable FDAI revision and scenario-set identity."""

    fdai_revision: str
    scenario_set_version: str

    def __post_init__(self) -> None:
        if _GIT_REVISION.fullmatch(self.fdai_revision) is None:
            raise ValueError("learning release FDAI revision MUST be immutable")
        if _IDENTIFIER.fullmatch(self.scenario_set_version) is None:
            raise ValueError("learning release scenario set MUST be canonical")


@dataclass(frozen=True, slots=True)
class EligibleOperationalOutcome:
    """Exact source, action, effect, and audit lineage for one case."""

    release: PinnedLearningRelease
    correlation_digest: str
    purpose: str
    access_scope_digest: str
    redaction_policy_version: str
    event_time_cutoff: datetime
    reviewed_at: datetime
    maximum_age: timedelta
    failure_fingerprint: FailureFingerprint
    action_type: str
    outcome_class: OperationalOutcomeClass
    source_kind: OperationalEvidenceSourceKind
    source_identity_digest: str
    source_synthetic: bool
    evidence_complete: bool
    conflict_digests: tuple[str, ...]
    receipts: tuple[OperationalReceiptFact, ...]

    def to_case_input(self) -> OperationalCaseInput:
        """Return the immutable case input, or reject an ineligible outcome."""

        if self.event_time_cutoff.tzinfo is None or self.reviewed_at.tzinfo is None:
            raise ValueError("eligible outcome timestamps MUST be timezone-aware")
        if self.maximum_age <= timedelta(0):
            raise ValueError("eligible outcome maximum age MUST be positive")
        if self.event_time_cutoff > self.reviewed_at:
            raise ValueError("eligible outcome cutoff MUST not be in the future")
        if self.reviewed_at - self.event_time_cutoff > self.maximum_age:
            raise ValueError("eligible outcome evidence is stale")
        if not self.evidence_complete:
            raise ValueError("eligible outcome evidence is incomplete")
        if self.conflict_digests:
            raise ValueError("eligible outcome evidence is conflicting")
        if self.source_kind is OperationalEvidenceSourceKind.LIVE and self.source_synthetic:
            raise ValueError("synthetic evidence MUST NOT be labeled live")
        if _SHA256.fullmatch(self.source_identity_digest) is None:
            raise ValueError("eligible outcome source identity MUST be SHA-256")
        receipt_types = {receipt.receipt_type for receipt in self.receipts}
        if receipt_types != {
            OperationalReceiptType.AUDIT,
            OperationalReceiptType.ACTION,
            OperationalReceiptType.RESPONSE_OUTCOME,
        }:
            raise ValueError("eligible outcome requires exact audit, action, and response receipts")
        evidence_refs = tuple(
            sorted(
                {
                    self.source_identity_digest,
                    *(receipt.receipt_digest for receipt in self.receipts),
                }
            )
        )
        identity_material = {
            "action_type": self.action_type,
            "correlation_digest": self.correlation_digest,
            "event_time_cutoff": self.event_time_cutoff.isoformat(),
            "failure_fingerprint": self.failure_fingerprint.digest,
            "fdai_revision": self.release.fdai_revision,
            "outcome_class": self.outcome_class.value,
            "receipt_digests": evidence_refs,
            "scenario_set_version": self.release.scenario_set_version,
            "source_kind": self.source_kind.value,
        }
        case_identity = hashlib.sha256(
            json.dumps(
                identity_material,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return OperationalCaseInput(
            case_identity_digest=case_identity,
            kind=CaseKind.ACTION,
            correlation_digest=self.correlation_digest,
            purpose=self.purpose,
            access_scope_digest=self.access_scope_digest,
            redaction_policy_version=self.redaction_policy_version,
            event_time_cutoff=self.event_time_cutoff,
            failure_fingerprint=self.failure_fingerprint,
            action_type=self.action_type,
            outcome_class=self.outcome_class,
            evidence_refs=evidence_refs,
            receipts=self.receipts,
            fdai_revision=self.release.fdai_revision,
            scenario_set_version=self.release.scenario_set_version,
            source_kind=self.source_kind,
            source_identity_digest=self.source_identity_digest,
            source_synthetic=self.source_synthetic,
            evidence_complete=self.evidence_complete,
            conflict_digests=self.conflict_digests,
        )


def operational_case_event(case_input: OperationalCaseInput) -> dict[str, object]:
    """Build the replay-stable raw event consumed by Huginn and Muninn."""

    event_id = f"operational-case:{case_input.case_identity_digest}"
    return {
        "id": event_id,
        "event_id": event_id,
        "correlation_id": case_input.correlation_digest,
        "idempotency_key": event_id,
        "source": "fdai.operational-learning",
        "event_type": "case_history.operational_case.v1",
        "resource_id": case_input.failure_fingerprint.digest,
        "attributes": case_input.to_mapping(),
    }


__all__ = [
    "EligibleOperationalOutcome",
    "PinnedLearningRelease",
    "operational_case_event",
]
