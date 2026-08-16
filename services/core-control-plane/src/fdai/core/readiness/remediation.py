"""Grounded remediation proposals derived from one operational-readiness review.

The Operational Readiness Review (ORR) is a read-only reviewer
(``docs/roadmap/operations/operational-readiness.md`` "Action bridging"): it
proposes, a distinct human approves, and the normal ``risk-gate -> executor``
path disposes. This module is the pure, deterministic bridge between a composed
:class:`~fdai.core.readiness.report.ReadinessReport` and the typed proposal the
delivery layer hands to that path.

Design invariants
-----------------

- **Grounded only**: a proposal exists only when a finding's cited rule or
  control maps to a remediation ActionType through the caller-supplied lever
  map. The builder never invents a lever from a resource name or a severity.
- **Shadow only**: every proposal carries :attr:`Mode.SHADOW`. The ORR cannot
  raise an ActionType above its own promotion state, so it never emits an
  auto-executable proposal.
- **No executor identity**: a proposal records the submitter and the distinct
  approver as accountability facts only. It carries no credential, no token,
  and no executor principal.
- **No self-approval**: the handoff submitter cannot approve their own
  remediation; that raises :class:`SelfApprovalError` before any proposal is
  built.
- **Deterministic identity**: the same report, finding, and lever always derive
  the same idempotency key, so a redelivered proposal is a no-op downstream.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.readiness.report import ReadinessFinding, ReadinessReport
from fdai.shared.contracts.models import Mode

_KEY_PREFIX = "orr-remediation"


class SelfApprovalError(ValueError):
    """Raised when the handoff submitter tries to approve their own review."""


def _principal_key(value: str) -> str:
    """Compare principals without letting encoding variance defeat the check.

    NFKC folding first means a visually identical but differently encoded
    submitter cannot approve their own review.
    """
    return unicodedata.normalize("NFKC", value).strip().casefold()


@dataclass(frozen=True, slots=True)
class HandoffApproval:
    """One distinct principal's decision to let ORR remediations be proposed.

    ``approver`` is a human App Role principal, never the executor workload
    identity. ``decided_at`` is an ISO-8601 timestamp recorded for audit and
    replay; the builder treats it as an opaque, non-empty string so a fork can
    supply its own clock.
    """

    approver: str
    decided_at: str

    def __post_init__(self) -> None:
        if not self.approver.strip():
            raise ValueError("HandoffApproval.approver MUST be non-empty")
        if not self.decided_at.strip():
            raise ValueError("HandoffApproval.decided_at MUST be non-empty")


@dataclass(frozen=True, slots=True)
class RemediationProposal:
    """One shadow remediation proposal bound to a grounded ORR finding."""

    action_type: str
    resource_ref: str
    scope: str
    target_environment: str
    submitter: str
    approver: str
    approved_at: str
    evidence: str
    severity: str
    blocking: bool
    idempotency_key: str
    dimension: str | None = None
    control_id: str | None = None
    mode: Mode = Mode.SHADOW

    def __post_init__(self) -> None:
        if self.mode is not Mode.SHADOW:
            raise ValueError("RemediationProposal.mode MUST remain shadow")

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly serialization for the proposal publisher seam."""
        return {
            "kind": "operational_readiness.remediation_proposal",
            "action_type": self.action_type,
            "resource_ref": self.resource_ref,
            "scope": self.scope,
            "target_environment": self.target_environment,
            "submitter": self.submitter,
            "approver": self.approver,
            "approved_at": self.approved_at,
            "evidence": self.evidence,
            "severity": self.severity,
            "blocking": self.blocking,
            "idempotency_key": self.idempotency_key,
            "dimension": self.dimension,
            "control_id": self.control_id,
            "mode": self.mode.value,
        }


def remediation_idempotency_key(
    *,
    scope: str,
    target_environment: str,
    evidence: str,
    resource_ref: str,
    action_type: str,
) -> str:
    """Derive the stable proposal identity for one finding and lever."""
    # Length-prefix every component: a separator inside a field must not let two
    # different findings derive one key and silently suppress a real proposal.
    parts = (scope, target_environment, evidence, resource_ref, action_type)
    material = "|".join(f"{len(part.encode('utf-8'))}:{part}" for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{_KEY_PREFIX}:{digest[:32]}"


def _lever_for(finding: ReadinessFinding, levers: Mapping[str, str]) -> str | None:
    """Resolve the remediation ActionType a finding's own citation declares."""
    for citation in (finding.control_id, finding.evidence):
        if not citation:
            continue
        lever = levers.get(citation)
        if lever is None:
            continue
        if not isinstance(lever, str) or not lever.strip():
            raise ValueError(f"remediation lever for {citation!r} MUST be a non-empty ActionType")
        return lever.strip()
    return None


def build_remediation_proposals(
    *,
    report: ReadinessReport,
    approval: HandoffApproval,
    remediation_levers: Mapping[str, str],
) -> tuple[RemediationProposal, ...]:
    """Build the deterministic shadow proposals this review can ground.

    Raises :class:`SelfApprovalError` when the approver is the handoff
    submitter. A finding with no mapped lever yields no proposal: the ORR
    abstains rather than inventing a remediation it cannot cite.
    """
    if _principal_key(approval.approver) == _principal_key(report.submitter):
        raise SelfApprovalError(
            "operational-readiness remediation requires an approver distinct from the submitter"
        )

    proposals: dict[str, RemediationProposal] = {}
    for finding in report.findings:
        lever = _lever_for(finding, remediation_levers)
        if lever is None:
            continue
        key = remediation_idempotency_key(
            scope=report.scope,
            target_environment=report.target_environment,
            evidence=finding.evidence,
            resource_ref=finding.resource,
            action_type=lever,
        )
        if key in proposals:
            continue
        proposals[key] = RemediationProposal(
            action_type=lever,
            resource_ref=finding.resource,
            scope=report.scope,
            target_environment=report.target_environment,
            submitter=report.submitter,
            approver=approval.approver,
            approved_at=approval.decided_at,
            evidence=finding.evidence,
            severity=finding.severity,
            blocking=finding.blocking,
            idempotency_key=key,
            dimension=finding.dimension,
            control_id=finding.control_id,
        )
    return tuple(proposals.values())


__all__ = [
    "HandoffApproval",
    "RemediationProposal",
    "SelfApprovalError",
    "build_remediation_proposals",
    "remediation_idempotency_key",
]
