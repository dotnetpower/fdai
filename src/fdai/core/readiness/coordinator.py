"""The ORR coordinator - compose the two review passes into one handoff verdict.

A pure fold: it takes the findings the whole-scope assurance-twin posture pass
and the deploy-preflight feasibility pass already produced (both shared value
types) and composes them into a single :class:`ReadinessReport`, applying the
environment gate. Running the two subsystems and delivering the report are the
caller's job (composition root / event-ingest); this stays deterministic and
I/O-free so a replay reproduces the verdict exactly.

Per operational-readiness.md "Module placement", the coordinator imports only
``shared/`` contracts and providers - it never reaches a sibling core subsystem,
a cloud SDK, or a privileged identity.
"""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.readiness.report import (
    HandoffVerdict,
    ReadinessFinding,
    ReadinessReport,
)
from fdai.core.readiness.signal import OwnershipTransfer
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import FindingSeverity, ProbeFinding
from fdai.shared.providers.projection import Finding, Severity

# Severity ordering shared with the posture report; kept local so the coordinator
# imports only shared types (no core-sibling dependency).
_SEVERITY_ORDER: tuple[Severity, ...] = ("low", "medium", "high", "critical")
_SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
# An unrecognized severity outranks every known one, so a finding whose severity
# the coordinator does not understand fails toward safety (treated as blocking)
# rather than crashing the whole handoff gate. Severity is a Literal, not a
# runtime-checked enum, so a fork projection or a deserialized finding can carry
# an unexpected value.
_UNKNOWN_SEVERITY_RANK = len(_SEVERITY_ORDER)


def _severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, _UNKNOWN_SEVERITY_RANK)


# The stages that resolve to non-prod on the authoritative runtime classifier
# (risk-classification.md Environment Detection / Promotion). Everything else -
# `prod`, `production`, an unknown word, or a blank - resolves to prod, the
# documented fail-safe (an un-tagged / unrecognized handoff is gated at the
# strictest level, never the weakest).
_NON_PROD_STAGES: frozenset[str] = frozenset({"non-prod", "dev", "test", "staging", "qa"})


def _is_prod_target(target_environment: str) -> bool:
    """True when the handoff target is gated as prod.

    Fail-safe per risk-classification.md: only a recognized non-prod stage
    (case-insensitive) escapes the prod gate; `production`, an unknown value, or
    a blank all resolve to prod - the exact opposite of an ``== "prod"`` check,
    which would fail open on `production` / unknown.
    """
    return target_environment.strip().lower() not in _NON_PROD_STAGES


def compose_readiness_report(
    *,
    signal: OwnershipTransfer,
    posture_findings: Sequence[Finding],
    preflight_findings: Sequence[ProbeFinding],
    mode: Mode,
    generated_at: str,
    blocking_min_severity: Severity = "high",
) -> ReadinessReport:
    """Compose the posture + preflight findings into one handoff verdict.

    A posture finding gates when its severity is at or above
    ``blocking_min_severity`` (config; default ``high``), OR - the environment
    gate - the target is ``prod`` and the finding is ``critical``, regardless of
    the threshold (operational-readiness.md "Environment promotion"). A preflight
    finding gates when its own severity is ``BLOCKING``. The verdict is
    ``blocked`` if any finding gates, ``needs_review`` if findings exist but none
    gates, ``clear`` if there are none.

    A posture finding whose severity is not one of the known levels fails toward
    safety (treated as blocking). ``blocking_min_severity`` is config and MUST be
    a known level - an invalid value raises :class:`ValueError` at the boundary.
    """
    if blocking_min_severity not in _SEVERITY_RANK:
        raise ValueError(
            f"blocking_min_severity {blocking_min_severity!r} is not a known severity "
            f"(expected one of {list(_SEVERITY_ORDER)})"
        )
    min_rank = _SEVERITY_RANK[blocking_min_severity]
    # Match the prod environment fail-safe (risk-classification.md): `prod`,
    # `production`, an unknown word, or a blank all gate as prod - only a
    # recognized non-prod stage escapes it. The report still records the
    # operator's original environment string; only the gate decision is derived.
    prod = _is_prod_target(signal.target_environment)
    findings: list[ReadinessFinding] = []

    for f in posture_findings:
        blocking = _severity_rank(f.severity) >= min_rank or (prod and f.severity == "critical")
        findings.append(
            ReadinessFinding(
                evidence=f.rule_id,
                severity=f.severity,
                resource=f.resource.ref,
                blocking=blocking,
                # The delivery layer resolves the remediation lever from the
                # cited rule; the coordinator never invents one.
                resolution=None,
                source="assurance_twin",
            )
        )

    for pf in preflight_findings:
        findings.append(
            ReadinessFinding(
                evidence=pf.id,
                severity=pf.severity.value,
                resource=signal.scope,
                blocking=pf.severity is FindingSeverity.BLOCKING,
                resolution=pf.resolution.guidance,
                source="deploy_preflight",
                dimension=pf.category.value,
            )
        )

    findings_t = tuple(findings)
    if not findings_t:
        verdict = HandoffVerdict.CLEAR
    elif any(f.blocking for f in findings_t):
        verdict = HandoffVerdict.BLOCKED
    else:
        verdict = HandoffVerdict.NEEDS_REVIEW

    return ReadinessReport(
        scope=signal.scope,
        submitter=signal.submitter,
        target_environment=signal.target_environment,
        generated_at=generated_at,
        mode=mode,
        verdict=verdict,
        findings=findings_t,
    )


__all__ = ["compose_readiness_report"]
