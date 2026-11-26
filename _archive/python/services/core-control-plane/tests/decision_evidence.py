"""Test-only decision-evidence admission provider."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission


class StubDecisionEvidenceAdmissionProvider:
    """Return input-bound admissions without providing production trust."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        now = self._now()
        return DecisionEvidenceAdmission(
            receipt_digest="sha256:" + "d" * 64,
            verification_bundle_digest="sha256:" + "e" * 64,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=now - timedelta(minutes=1),
            valid_until=now + timedelta(minutes=1),
        )


__all__ = ["StubDecisionEvidenceAdmissionProvider"]
