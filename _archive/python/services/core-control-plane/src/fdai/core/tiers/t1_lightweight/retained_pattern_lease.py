"""Authority-free evidence accepted only while an owning source lease is held."""

from __future__ import annotations

import re
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)

from .retained_pattern_bindings import RetainedPatternQualification


@dataclass(frozen=True, slots=True)
class RetainedPatternLeaseEvidence:
    tuple_digest: str
    scope_digest: str
    dependencies_digest: str
    valid_until: datetime
    read_admission: DecisionEvidenceAdmission
    reuse_admission: DecisionEvidenceAdmission
    guard: LeaseGuard = field(default_factory=lambda: LeaseGuard())

    def current(self, request: RetainedPatternQualification, *, now: datetime) -> bool:
        value = request.descriptor
        read, reuse = value["read"], value["reuse"]
        args, principal = read["arguments"], read["principal"]
        if (
            not self.guard.active
            or re.fullmatch(r"sha256:[a-f0-9]{64}", self.dependencies_digest) is None
            or self.tuple_digest != request.evidence_digest
            or self.scope_digest != request.scope_digest
            or now >= self.valid_until
            or self.valid_until
            > min(self.read_admission.valid_until, self.reuse_admission.valid_until)
            or self.reuse_admission.to_mapping() != reuse["admission"]
        ):
            return False
        pairs = (
            (
                self.read_admission,
                {
                    "evidence": content_digest({"arguments": args, "principal": principal}),
                    "scope": content_digest(
                        {
                            "principal_scope": principal["principal_scope_digest"],
                            "case_scope": args["access_scope_digest"],
                            "purpose": args["purpose"],
                        }
                    ),
                    "purpose": "case-history-read",
                    "revision": read["source_revision"],
                },
            ),
            (
                self.reuse_admission,
                {
                    "evidence": reuse["evidence_digest"],
                    "scope": reuse["scope_digest"],
                    "purpose": "current-case-reuse",
                    "revision": value["match"]["context"]["graph_digest"],
                },
            ),
        )
        return not any(
            now >= admission.valid_until
            or assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=expected["evidence"],
                expected_scope_digest=expected["scope"],
                expected_purpose_id=expected["purpose"],
                expected_source_revision=expected["revision"],
                evaluated_at=now,
            )
            for admission, expected in pairs
        )


@dataclass(slots=True)
class LeaseGuard:
    """In-process lifetime marker; it is neither an epoch nor a permission."""

    active: bool = False


def retained_pattern_lease_current(
    evidence: RetainedPatternLeaseEvidence,
    request: RetainedPatternQualification,
    *,
    now: datetime,
) -> bool:
    """Resolve the shared read/reuse admissions while the owning lease is active."""
    return evidence.current(request, now=now)


class RetainedPatternLeasedQualifier(Protocol):
    """Keep actual owner guards held until the caller accepts the positive comparison."""

    def lease(
        self, request: RetainedPatternQualification
    ) -> AbstractAsyncContextManager[RetainedPatternLeaseEvidence | None]: ...
