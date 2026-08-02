"""Assurance Twin - :class:`PostureAssessmentReport` assembly (Wave A.5).

Assembles a subscription-scope posture report from the findings the
Twin's projection produced. This is the whole-estate generalization of
:class:`~fdai.core.deploy_preflight.report.DeploymentReadinessReport`
(single-deploy verdict), promised in
[assurance-twin.md](../../../../docs/roadmap/operations/assurance-twin.md) as the
Twin's on-demand assessment output.

Design invariants
-----------------

- **Read-only, pure**: assembly is a deterministic fold over a bounded
  ``Sequence[Finding]``; no I/O, no cloud SDK, no LLM. Same input yields
  identical output byte for byte.
- **Grounded by construction**: every entry keeps the three required
  parts declared in the doc - the ``rule_id`` (cited evidence), the
  ``severity``, and the source resource. The console renders the
  ``resolution`` lever by looking up the rule; this module does not
  invent one.
- **Shadow-first**: like the Preflight report, ``blocks_action`` is
  ``True`` only when the pass ran in ``enforce`` mode AND the verdict is
  BLOCKED. Shadow passes still record the truthful verdict; they never
  gate an autonomous action.
- **CSP-neutral**: consumes only ``shared/providers/projection`` types.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, Severity

# Ordered from least to most severe. Used to compute the aggregate
# ``highest_severity`` in one pass without exposing severity ordering
# elsewhere.
_SEVERITY_ORDER: tuple[Severity, ...] = ("low", "medium", "high", "critical")
_SEVERITY_RANK: Mapping[Severity, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
# A finding at or above this severity is considered a blocker for the
# purpose of the aggregate report verdict. Individual consumers (e.g. a
# per-vertical panel) MAY apply a stricter threshold; the shipped default
# matches how the Preflight report treats ``blocking`` (high + critical).
_BLOCKING_MIN_RANK: int = _SEVERITY_RANK["high"]


class PostureVerdict(StrEnum):
    """Truthful classification of a whole-estate posture report."""

    CLEAR = "clear"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PostureAssessmentReport:
    """Whole-subscription posture on demand.

    A grounded, deterministic snapshot: every entry cites the rule that
    produced it, and the aggregate verdict is derived from the findings,
    never invented. The delivery layer (console `ReadPanel` /
    operator-api HIL queue) renders this without a privileged call.
    """

    scope: str
    generated_at: str
    mode: Mode
    verdict: PostureVerdict
    findings: tuple[Finding, ...]

    @property
    def resource_count(self) -> int:
        """Number of distinct resources touched by any finding."""

        return len({f.resource for f in self.findings})

    @property
    def rule_count(self) -> int:
        """Number of distinct rule ids that produced a finding."""

        return len({f.rule_id for f in self.findings})

    @property
    def highest_severity(self) -> Severity | None:
        """Return the most severe finding's severity, or ``None``."""

        if not self.findings:
            return None
        return _SEVERITY_ORDER[max(_SEVERITY_RANK[f.severity] for f in self.findings)]

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        """Findings whose severity is at or above the blocker threshold."""

        return tuple(f for f in self.findings if _SEVERITY_RANK[f.severity] >= _BLOCKING_MIN_RANK)

    @property
    def severity_counts(self) -> Mapping[Severity, int]:
        """Per-severity finding count (every severity always present)."""

        counts: dict[Severity, int] = {s: 0 for s in _SEVERITY_ORDER}
        for f in self.findings:
            counts[f.severity] += 1
        return counts

    @property
    def blocks_action(self) -> bool:
        """True only when authoritative (enforce) AND at least one blocker.

        Shadow passes report blockers but never gate an action, matching
        the shadow-first contract in
        [architecture.instructions.md](../../../../.github/instructions/architecture.instructions.md).
        """

        return self.mode is Mode.ENFORCE and self.verdict is PostureVerdict.BLOCKED

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly serialization for delivery adapters."""

        return {
            "scope": self.scope,
            "generated_at": self.generated_at,
            "mode": self.mode.value,
            "verdict": self.verdict.value,
            "blocks_action": self.blocks_action,
            "resource_count": self.resource_count,
            "rule_count": self.rule_count,
            "highest_severity": self.highest_severity,
            "severity_counts": dict(self.severity_counts),
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "resource_type": f.resource.resource_type,
                    "resource_ref": f.resource.ref,
                    "severity": f.severity,
                    "reason": f.reason,
                    "evidence_refs": list(f.evidence_refs),
                }
                for f in self.findings
            ],
        }


def build_posture_assessment_report(
    *,
    scope: str,
    generated_at: str,
    mode: Mode,
    findings: Sequence[Finding],
) -> PostureAssessmentReport:
    """Assemble a :class:`PostureAssessmentReport` from a bounded finding set.

    The verdict is derived, not passed in:

    - No findings -> ``CLEAR``.
    - Findings but none at or above the blocker threshold -> ``NEEDS_REVIEW``.
    - At least one blocker-severity finding -> ``BLOCKED``.

    The mode flag records whether the pass was authoritative; the
    verdict is truthful regardless of mode (shadow surfaces the same
    ``BLOCKED`` when a blocker exists), but ``blocks_action`` remains
    ``False`` for shadow so the report can never gate a change on its
    own. Duplicate ``(rule_id, resource)`` pairs are preserved verbatim
    - the caller decides whether to de-duplicate upstream because two
    rules matching the same resource independently is legitimate.
    """

    if not scope:
        raise ValueError("scope MUST be a non-empty string")
    if not generated_at:
        raise ValueError("generated_at MUST be a non-empty string")

    frozen = tuple(findings)
    if not frozen:
        verdict = PostureVerdict.CLEAR
    elif any(_SEVERITY_RANK[f.severity] >= _BLOCKING_MIN_RANK for f in frozen):
        verdict = PostureVerdict.BLOCKED
    else:
        verdict = PostureVerdict.NEEDS_REVIEW

    return PostureAssessmentReport(
        scope=scope,
        generated_at=generated_at,
        mode=mode,
        verdict=verdict,
        findings=frozen,
    )


__all__ = [
    "PostureAssessmentReport",
    "PostureVerdict",
    "build_posture_assessment_report",
]
