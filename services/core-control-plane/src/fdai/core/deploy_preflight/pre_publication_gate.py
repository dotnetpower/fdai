"""Pre-publication gate - re-verify a reassembly before any proposal is submitted.

The bounded loop in :mod:`fdai.core.deploy_preflight.reassemble` decides *what*
to reassemble and :mod:`fdai.core.deploy_preflight.reassembly_proposals` renders
one proposal per applied toggle. This module is the last deterministic check
between those decisions and the governed pipeline seam
(``ProposalSink`` -> Huginn -> Forseti -> Var -> Thor): it invokes the analyzer
once more on the accumulated overrides and submits nothing unless that fresh
report clears publication.

Design: ``docs/roadmap/deployment/deployment-preflight.md`` and
``docs/roadmap/deployment/preflight-active-reassembly.md``.

Why a separate gate
-------------------
Execution eligibility is granted by verification, never by the fix generator.
A reassembly outcome is a decision taken at some earlier moment; the report that
justified it can be blocked, stale, or bound to another scope by the time a
remediation PR would be published. The gate re-asks the same analyzer and routes
every unproven case to human review instead of the pipeline, so a blocking
finding, an escalated loop, stale evidence, or a scope change prevents the later
provider commit.

Boundaries
----------
Pure ``core/`` logic. This module constructs no cloud SDK, opens no PR, runs no
terraform, and executes nothing. It calls one injected ``verify`` callable and,
only on a clean verdict, the injected sink. A raising ``verify`` propagates
before any submission (fail-closed); the caller degrades to ``hil``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.core.deploy_preflight.reassemble import ReassemblyOutcome, ReassemblyStatus
from fdai.core.deploy_preflight.reassembly_proposals import (
    ProposalSink,
    ToggleActionProposal,
    build_toggle_proposals,
)
from fdai.core.deploy_preflight.report import DeploymentReadinessReport

#: Default freshness window for the pre-publication report. Configuration, not
#: policy: a fork tunes it at the composition root. Kept short so a report that
#: predates the publication attempt cannot authorize a provider commit.
DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 900.0

#: Tolerated clock skew for a report stamped slightly in the future. Anything
#: beyond it is treated as unusable evidence rather than fresh evidence.
_MAX_CLOCK_SKEW_SECONDS = 60.0

#: An async callable the caller injects: given the accumulated tfvars overrides,
#: re-render, re-plan, and re-analyze the deployment, returning a fresh report.
#: Same shape as :data:`fdai.core.deploy_preflight.reassemble.ReanalyzeFn`.
VerifyFn = Callable[[Mapping[str, str]], Awaitable[DeploymentReadinessReport]]


class PublicationDecision(StrEnum):
    """What the gate decided about submitting toggle proposals."""

    SUBMIT = "submit"
    """The fresh report cleared publication; proposals were submitted."""

    NO_ACTION = "no_action"
    """Nothing to publish - the pass applied no toggle."""

    HUMAN_REVIEW = "human_review"
    """Publication withheld; the caller routes the pass to ``hil``."""


class PublicationHold(StrEnum):
    """Why publication was withheld (audit-grade, content-free)."""

    NONE = "none"
    """Not withheld."""

    NO_APPLIED_TOGGLE = "no_applied_toggle"
    """The outcome cleared without applying a toggle, so there is nothing to publish."""

    REASSEMBLY_ESCALATED = "reassembly_escalated"
    """The loop escalated; a partial reassembly is never submitted."""

    BLOCKING_FINDING = "blocking_finding"
    """The re-verified report still carries at least one blocking finding."""

    STALE_EVIDENCE = "stale_evidence"
    """The report's ``generated_at`` is outside the freshness window or unusable."""

    SCOPE_DRIFT = "scope_drift"
    """The verified report or an applied toggle does not bind the expected scope."""


@dataclass(frozen=True, slots=True)
class PublicationGateOutcome:
    """The gate's decision plus the evidence that produced it."""

    decision: PublicationDecision
    hold: PublicationHold
    proposals: tuple[ToggleActionProposal, ...] = ()
    submitted: tuple[Mapping[str, Any] | None, ...] = ()
    report: DeploymentReadinessReport | None = None
    evidence_age_seconds: float | None = None
    expected_scope: str | None = None
    held_findings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def publishes(self) -> bool:
        """True only when proposals actually reached the pipeline sink."""

        return self.decision is PublicationDecision.SUBMIT

    def to_dict(self) -> dict[str, Any]:
        """Serialize the decision for an audit or human-review record."""

        return {
            "decision": self.decision.value,
            "hold": self.hold.value,
            "proposal_count": len(self.proposals),
            "submitted_count": len(self.submitted),
            "expected_scope": self.expected_scope,
            "evidence_age_seconds": self.evidence_age_seconds,
            "held_findings": list(self.held_findings),
            "verdict": self.report.verdict.value if self.report is not None else None,
        }


def _utc_now() -> datetime:
    """Default clock. Injected in tests."""

    return datetime.now(UTC)


def _evidence_age_seconds(report: DeploymentReadinessReport, now: datetime) -> float | None:
    """Return the report's age in seconds, or ``None`` when it is unusable."""

    try:
        generated_at = datetime.fromisoformat(report.generated_at)
    except ValueError:
        return None
    if generated_at.tzinfo is None:
        return None
    return (now - generated_at).total_seconds()


def _hold(
    hold: PublicationHold,
    *,
    proposals: tuple[ToggleActionProposal, ...] = (),
    report: DeploymentReadinessReport | None = None,
    evidence_age_seconds: float | None = None,
    expected_scope: str | None = None,
    held_findings: tuple[str, ...] = (),
) -> PublicationGateOutcome:
    return PublicationGateOutcome(
        decision=PublicationDecision.HUMAN_REVIEW,
        hold=hold,
        proposals=proposals,
        report=report,
        evidence_age_seconds=evidence_age_seconds,
        expected_scope=expected_scope,
        held_findings=held_findings,
    )


async def gate_toggle_publication(
    outcome: ReassemblyOutcome,
    *,
    verify: VerifyFn,
    sink: ProposalSink,
    initiator_principal: str,
    expected_scope: str,
    reason: str | None = None,
    max_evidence_age_seconds: float = DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
    now: Callable[[], datetime] = _utc_now,
) -> PublicationGateOutcome:
    """Re-verify ``outcome`` and submit its proposals only when publication clears.

    The order is a safety property: every hold is decided *before* the first
    ``sink`` call, so a withheld pass never submits a partial set of proposals.
    Submission itself is delegated to the same envelope builder an operator
    command re-enters through, so the executor keeps the seven safeguards.

    Propagates any exception raised by ``verify`` or ``sink`` (fail-closed).
    """

    if max_evidence_age_seconds <= 0:
        raise ValueError("max_evidence_age_seconds MUST be > 0")
    if not expected_scope.strip():
        raise ValueError("expected_scope MUST be a non-empty string")

    if outcome.status is not ReassemblyStatus.CLEARED:
        return _hold(PublicationHold.REASSEMBLY_ESCALATED, expected_scope=expected_scope)

    proposals = build_toggle_proposals(
        outcome, initiator_principal=initiator_principal, reason=reason
    )
    if not proposals:
        return PublicationGateOutcome(
            decision=PublicationDecision.NO_ACTION,
            hold=PublicationHold.NO_APPLIED_TOGGLE,
            expected_scope=expected_scope,
        )

    if any(proposal.scope != expected_scope for proposal in proposals):
        return _hold(
            PublicationHold.SCOPE_DRIFT, proposals=proposals, expected_scope=expected_scope
        )

    # Verification, not the reassembly decision, grants publication eligibility.
    report = await verify(dict(outcome.overrides))

    if report.scope != expected_scope:
        return _hold(
            PublicationHold.SCOPE_DRIFT,
            proposals=proposals,
            report=report,
            expected_scope=expected_scope,
        )

    age = _evidence_age_seconds(report, now())
    if age is None or age > max_evidence_age_seconds or age < -_MAX_CLOCK_SKEW_SECONDS:
        return _hold(
            PublicationHold.STALE_EVIDENCE,
            proposals=proposals,
            report=report,
            evidence_age_seconds=age,
            expected_scope=expected_scope,
        )

    # The truthful verdict gates publication even in shadow mode, where
    # ``blocks_deploy`` stays False because the probe set is unproven.
    blocking = report.blocking_findings
    if blocking:
        return _hold(
            PublicationHold.BLOCKING_FINDING,
            proposals=proposals,
            report=report,
            evidence_age_seconds=age,
            expected_scope=expected_scope,
            held_findings=tuple(sorted(finding.id for finding in blocking)),
        )

    submitted: list[Mapping[str, Any] | None] = []
    for proposal in proposals:
        submitted.append(await sink(proposal.to_dict()))
    return PublicationGateOutcome(
        decision=PublicationDecision.SUBMIT,
        hold=PublicationHold.NONE,
        proposals=proposals,
        submitted=tuple(submitted),
        report=report,
        evidence_age_seconds=age,
        expected_scope=expected_scope,
    )


__all__ = [
    "DEFAULT_MAX_EVIDENCE_AGE_SECONDS",
    "PublicationDecision",
    "PublicationGateOutcome",
    "PublicationHold",
    "VerifyFn",
    "gate_toggle_publication",
]
