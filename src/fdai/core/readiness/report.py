"""The :class:`ReadinessReport` - a generalization of the
:class:`~fdai.core.assurance_twin.report.PostureAssessmentReport` bound to an
``ownership_transfer`` event.

Verdict semantics (operational-readiness.md):

- ``clear`` - no findings.
- ``needs_review`` - findings exist but none is blocking (warnings only).
- ``blocked`` - at least one blocking finding.

The report always records the **truthful** verdict; whether that verdict *gates*
the handoff is the separate :meth:`ReadinessReport.blocks_handoff` flag, true
only when the ORR ran in ``enforce`` mode - the same truthful-verdict /
separate-gate split the Preflight ``blocks_deploy`` and the posture
``blocks_action`` flags use.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.contracts.models import Mode


class HandoffVerdict(StrEnum):
    """Truthful classification of a dev-to-ops handoff review."""

    CLEAR = "clear"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ReadinessFinding:
    """One ORR finding, normalized from either source subsystem.

    Keeps the three doc-required parts: ``evidence`` (a CSP-neutral citation of
    the rule or probe that produced it - a finding that cannot cite a source is
    a defect), ``severity``, and ``resolution`` (a remediation ActionType id or
    guidance, or ``None`` when the delivery layer resolves the lever from the
    rule). ``blocking`` is the resolved gate flag (severity threshold + the
    prod environment gate); ``source`` names the producing subsystem.
    """

    evidence: str
    severity: str
    resource: str
    blocking: bool
    resolution: str | None
    source: str
    dimension: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence.strip():
            raise ValueError("ReadinessFinding.evidence MUST cite a rule/probe id")


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """The composed dev-to-ops handoff verdict for one ownership transfer."""

    scope: str
    submitter: str
    target_environment: str
    generated_at: str
    mode: Mode
    verdict: HandoffVerdict
    findings: tuple[ReadinessFinding, ...]

    @property
    def blocking_findings(self) -> tuple[ReadinessFinding, ...]:
        return tuple(f for f in self.findings if f.blocking)

    @property
    def blocks_handoff(self) -> bool:
        """True only when authoritative (enforce) AND the verdict is blocked.

        Shadow passes report blockers truthfully but never gate a real handoff,
        so an unproven review cannot stop a handoff on a false positive.
        """

        return self.mode is Mode.ENFORCE and self.verdict is HandoffVerdict.BLOCKED

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly serialization for delivery adapters."""

        return {
            "scope": self.scope,
            "submitter": self.submitter,
            "target_environment": self.target_environment,
            "generated_at": self.generated_at,
            "mode": self.mode.value,
            "verdict": self.verdict.value,
            "blocks_handoff": self.blocks_handoff,
            "findings": [
                {
                    "evidence": f.evidence,
                    "severity": f.severity,
                    "resource": f.resource,
                    "blocking": f.blocking,
                    "resolution": f.resolution,
                    "source": f.source,
                    "dimension": f.dimension,
                }
                for f in self.findings
            ],
        }


__all__ = ["HandoffVerdict", "ReadinessFinding", "ReadinessReport"]
