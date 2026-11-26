"""False-positive adjudication for claims returned from remediation sessions.

A coding agent can only *claim* a false positive. An authorized person decides, with a recorded
approval reference, and the decision is a typed record that Saga audits and Norns may use as a
rule-precision signal. The claimant and the adjudicator must be different principals, except in an
explicitly selected single-operator profile where one named operator holds every role.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.security.code_findings.result_import import ClaimStatus, IssueClaim

_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._:-]{0,127}$")
_APPROVAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")


class AdjudicationDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AdjudicationError(ValueError):
    """Raised when an adjudication request is not admissible."""


@dataclass(frozen=True, slots=True)
class FalsePositiveAdjudication:
    pack_id: str
    issue_id: str
    decision: AdjudicationDecision
    claimant: str
    adjudicator: str
    approval_ref: str
    rationale: str
    claim_evidence: str
    decided_at: datetime
    single_operator_profile: bool = False

    @property
    def issue_disposition(self) -> str:
        """Return the issue state after the decision: ``false_positive`` or ``open``."""
        return "false_positive" if self.decision is AdjudicationDecision.ACCEPTED else "open"


def adjudicate_false_positive(
    claim: IssueClaim,
    *,
    pack_id: str,
    claimant: str,
    adjudicator: str,
    approval_ref: str,
    decision: AdjudicationDecision,
    rationale: str,
    decided_at: datetime,
    single_operator_profile: bool = False,
) -> FalsePositiveAdjudication:
    """Return an adjudication record or raise :class:`AdjudicationError`."""
    if claim.status is not ClaimStatus.CLAIMED_FALSE_POSITIVE:
        raise AdjudicationError("only claimed_false_positive claims can be adjudicated")
    for name, value in (("claimant", claimant), ("adjudicator", adjudicator)):
        if _PRINCIPAL.fullmatch(value) is None:
            raise AdjudicationError(f"{name} must be a principal identifier")
    if _APPROVAL.fullmatch(approval_ref) is None:
        raise AdjudicationError("approval_ref must reference a recorded human approval")
    if claimant == adjudicator and not single_operator_profile:
        raise AdjudicationError("the claimant cannot adjudicate their own claim")
    if decided_at.tzinfo is None:
        raise AdjudicationError("decided_at must be timezone-aware")
    text = rationale.strip()
    if not 10 <= len(text) <= 2_000:
        raise AdjudicationError("rationale must be 10-2000 characters")
    return FalsePositiveAdjudication(
        pack_id=pack_id,
        issue_id=claim.issue_id,
        decision=decision,
        claimant=claimant,
        adjudicator=adjudicator,
        approval_ref=approval_ref,
        rationale=text,
        claim_evidence=claim.evidence,
        decided_at=decided_at,
        single_operator_profile=single_operator_profile,
    )


__all__ = [
    "AdjudicationDecision",
    "AdjudicationError",
    "FalsePositiveAdjudication",
    "adjudicate_false_positive",
]
