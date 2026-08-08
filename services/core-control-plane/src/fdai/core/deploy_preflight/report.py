"""Deployment readiness report - the assembled output of a preflight pass.

Produced by :class:`~fdai.core.deploy_preflight.analyzer.PreflightAnalyzer`
from the findings a set of probes return. This is an internally produced
artifact handed outward to delivery adapters (PR comment / GitHub Check /
read-only console), so it is a plain immutable value with a JSON-friendly
:meth:`DeploymentReadinessReport.to_dict`.

Verdict semantics
-----------------
- ``CLEAR`` - no findings at all.
- ``NEEDS_REVIEW`` - findings exist but none is blocking (warnings only),
  or the pass ran in shadow mode where blockers are reported but never gate.
- ``BLOCKED`` - at least one blocking finding and the pass ran in enforce
  mode.

Shadow-first (see ``docs/roadmap/deployment/deployment-preflight.md``): a probe that is
not yet proven runs in shadow, so :meth:`DeploymentReadinessReport.blocks_deploy`
stays ``False`` until the probe is promoted to enforce. The report always
records the truthful ``verdict`` regardless of mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    ProbeCategory,
    ProbeFinding,
)


class ReadinessVerdict(StrEnum):
    """Truthful classification of a readiness report."""

    CLEAR = "clear"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class DeploymentReadinessReport:
    """A single, grounded summary of everything that could block a deploy."""

    scope: str
    generated_at: str
    mode: Mode
    verdict: ReadinessVerdict
    findings: tuple[ProbeFinding, ...]
    checked_categories: tuple[ProbeCategory, ...]

    @property
    def blocking_findings(self) -> tuple[ProbeFinding, ...]:
        return tuple(f for f in self.findings if f.severity is FindingSeverity.BLOCKING)

    @property
    def blocks_deploy(self) -> bool:
        """True only when the pass is authoritative and found a blocker.

        Shadow-mode passes report blockers but never gate a deploy, so this
        is ``False`` unless ``mode`` is enforce and the verdict is blocked.
        """
        return self.mode is Mode.ENFORCE and self.verdict is ReadinessVerdict.BLOCKED

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain JSON-friendly dict for delivery adapters."""
        finding_counts = {
            category: sum(1 for finding in self.findings if finding.category is category)
            for category in self.checked_categories
        }
        return {
            "scope": self.scope,
            "generated_at": self.generated_at,
            "mode": self.mode.value,
            "verdict": self.verdict.value,
            "blocks_deploy": self.blocks_deploy,
            "checks": [
                {
                    "category": category.value,
                    "status": "finding" if finding_counts[category] else "clear",
                    "finding_count": finding_counts[category],
                }
                for category in self.checked_categories
            ],
            "findings": [f.to_dict() for f in self.findings],
        }
