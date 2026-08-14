"""T2 reasoning tier orchestrator - propose + quality-gate.

Phase 2 T2 (see [`docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.7`] and
[`architecture.instructions.md § LLM Quality Gate`]). Mirrors the T1 tier
structure: a small orchestrator over DI seams, no concrete LLM import in
``core/``.

Contract
--------

Given a novel / ambiguous :class:`Event` that T0 and T1 could not resolve, the
T2 tier asks an injected :class:`T2Proposer` (frontier-model backed in a fork)
for a :class:`~fdai.core.quality_gate.gate.QualityCandidate` - the ActionType +
params + cited rules it would emit. The candidate is then run through the
existing :class:`~fdai.core.quality_gate.gate.QualityGate` (mixed-model
cross-check + deterministic verifier + RAG grounding). The tier maps the gate's
outcome onto a tier decision the control loop routes to the risk-gate:

- gate ``ELIGIBLE`` -> :attr:`T2Outcome.PROPOSED` - the deterministic gate
  cleared the candidate; the risk-gate MAY consider auto-execution.
- gate ``ABSTAIN`` / ``DISAGREE`` -> :attr:`T2Outcome.ESCALATE` - hand off to
  HIL, never auto-resolve.
- gate ``DENY`` -> :attr:`T2Outcome.DENIED` - no execution.
- proposer returns ``None`` -> :attr:`T2Outcome.ABSTAIN` - nothing to gate.

Execution eligibility is granted by the deterministic gate, never by the
model's prose. The tier never executes; it returns a decision.

DI seams
--------

- :class:`T2Proposer` - turns an Event into a candidate action. Real backends
  (frontier LLMs behind the mixed-model cross-check) go in a fork; a test fake
  returns a preset candidate.
- :class:`QualityGateProtocol` - the quality gate. The concrete
  :class:`~fdai.core.quality_gate.gate.QualityGate` satisfies it structurally;
  tests inject a trivial fake to exercise the outcome mapping in isolation.
- :class:`~fdai.core.quality_gate.self_consistency.SelfConsistencyCascade` -
  optional cost-controlled stability measurement. When bound, a weak cheap
  signal triggers bounded resampling; the measured ``action_stability`` rides
  on the candidate into the quality decision and audit record, and an unstable
  proposer can only lower the outcome to :attr:`T2Outcome.ESCALATE`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.core.metering.budget import BudgetLedger, InMemoryBudgetLedger, ModelBudget
from fdai.core.quality_gate.gate import (
    QualityCandidate,
    QualityDecision,
    QualityOutcome,
)
from fdai.core.quality_gate.self_consistency import SelfConsistencyCascade
from fdai.core.tiers.t2_reasoning.recovery import T2ProposerBudgetExhaustedError
from fdai.shared.contracts.models import Event, Rule


class T2Outcome(StrEnum):
    """Terminal outcome for one :meth:`T2Tier.evaluate` call."""

    PROPOSED = "proposed"
    """Quality gate cleared the candidate; eligible for the risk-gate."""

    ESCALATE = "escalate"
    """Gate abstained, cross-check disagreed, or the budget is spent; route to HIL."""

    DENIED = "denied"
    """Verifier explicitly rejected the candidate; no execution."""

    ABSTAIN = "abstain"
    """The proposer produced no candidate; nothing to gate."""


@dataclass(frozen=True, slots=True)
class T2Decision:
    """Result of a T2 tier evaluation."""

    outcome: T2Outcome
    candidate: QualityCandidate | None
    quality_decision: QualityDecision | None
    reason: str

    @property
    def eligible_for_risk_gate(self) -> bool:
        """True only when the quality gate cleared the candidate."""
        return self.outcome is T2Outcome.PROPOSED


@dataclass(frozen=True, slots=True)
class T2ProposalContext:
    """Trusted, bounded input supplied to a T2 proposer."""

    event: Event
    target_resource_ref: str
    target_resource_type: str
    allowed_rules: tuple[Rule, ...]


@runtime_checkable
class T2Proposer(Protocol):
    """Produces a quality-gate candidate for a novel/ambiguous event."""

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        """Return a candidate action, or ``None`` to abstain.

        A fork's real proposer MUST populate
        :attr:`~fdai.core.quality_gate.gate.QualityCandidate.reasoning_trace`
        with the model's natural-language justification when the
        hallucination rubric leg is wired: the rubric scores that text
        for faithfulness, and a blank trace makes the rubric abstain
        (route to HIL) for lack of a scoring target. Leaving it empty is
        valid only when no rubric evaluator is bound.
        """
        ...


@runtime_checkable
class QualityGateProtocol(Protocol):
    """The quality gate seam the tier depends on (structural)."""

    async def evaluate(self, candidate: QualityCandidate) -> QualityDecision: ...


_OUTCOME_MAP = {
    QualityOutcome.ELIGIBLE: T2Outcome.PROPOSED,
    QualityOutcome.ABSTAIN: T2Outcome.ESCALATE,
    QualityOutcome.DISAGREE: T2Outcome.ESCALATE,
    QualityOutcome.DENY: T2Outcome.DENIED,
}


class T2Tier:
    """Frontier-model reasoning tier - propose, quality-gate, map."""

    __slots__ = ("_budget", "_ledger", "_proposer", "_quality_gate", "_self_consistency")

    def __init__(
        self,
        *,
        proposer: T2Proposer,
        quality_gate: QualityGateProtocol,
        budget: ModelBudget | None = None,
        budget_ledger: BudgetLedger | None = None,
        self_consistency: SelfConsistencyCascade | None = None,
    ) -> None:
        self._proposer = proposer
        self._quality_gate = quality_gate
        self._self_consistency = self_consistency
        # Call-denominated on purpose. The proposer meters its own
        # usage straight to the metering sink, so no cost ever lands on
        # this ledger: a money limb here would be a ceiling that can
        # never fire, which is worse than no ceiling because it reads
        # like one. The pipeline's money ceiling lives at the metering
        # write (``BudgetChargingMeteringSink``). An injected ledger is
        # used as given, so a deployment that does share one with
        # metering keeps its money limb.
        self._budget = replace(
            budget if budget is not None else ModelBudget(),
            max_cost_microusd_per_correlation=None,
            max_cost_microusd_total=None,
        )
        self._ledger: BudgetLedger = budget_ledger or InMemoryBudgetLedger(self._budget)

    async def evaluate(self, *, context: T2ProposalContext) -> T2Decision:
        """Propose a candidate for ``event`` and gate it.

        Fail-closed: an abstaining proposer or any non-eligible gate outcome
        yields a non-executing decision. Only a gate ``ELIGIBLE`` verdict
        makes the candidate eligible for the risk-gate.

        The declared model budget is checked first. An event that cannot
        be reasoned about within the ceiling escalates to HIL rather than
        spending past it, which is what ``cost-model.md`` requires:
        overflow degrades to a human, never to uncapped inference. The
        call is charged before the proposer runs, so a failing provider
        cannot be retried without limit.

        The budget is keyed by ``event_id``, not ``correlation_id``: a
        correlation id is the key a storm of related events *shares*
        (``core/event_ingest/correlator.py``), so keying by it would
        reason about the first event of an incident and escalate every
        later one. The pipeline's unit of work is the event.

        When a self-consistency cascade is bound it runs between the proposal
        and the gate. Its measured stability joins the candidate only when it
        is strictly below the current aggregate confidence, so the measurement
        can never raise it; a below-threshold measurement holds the outcome at
        :attr:`T2Outcome.ESCALATE` and a sampler failure escalates fail-closed.
        """
        budget_key = str(context.event.event_id)
        budgeted_propose = getattr(self._proposer, "propose_with_budget", None)
        try:
            if callable(budgeted_propose):
                candidate = await budgeted_propose(
                    context=context,
                    reserve_attempt=lambda: self._ledger.reserve(
                        budget_key,
                        calls=1,
                        cost_microusd=0,
                    ),
                )
            else:
                # Reserve atomically: asking whether the allowance fits and then
                # taking it lets two concurrent events past one declared total.
                if not await self._ledger.reserve(budget_key, calls=1, cost_microusd=0):
                    raise T2ProposerBudgetExhaustedError("T2 proposer budget exhausted")
                candidate = await self._proposer.propose(context=context)
        except T2ProposerBudgetExhaustedError:
            return T2Decision(
                outcome=T2Outcome.ESCALATE,
                candidate=None,
                quality_decision=None,
                reason="t2_budget_exhausted",
            )
        except Exception as exc:  # noqa: BLE001 - model/provider boundary
            return T2Decision(
                outcome=T2Outcome.ESCALATE,
                candidate=None,
                quality_decision=None,
                reason=f"t2_proposer_error:{type(exc).__name__}",
            )
        if candidate is None:
            return T2Decision(
                outcome=T2Outcome.ABSTAIN,
                candidate=None,
                quality_decision=None,
                reason="t2_proposer_abstained",
            )
        stability_hold = False
        if self._self_consistency is not None:
            try:
                cascade = await self._self_consistency.decide(
                    candidate,
                    aggregate_confidence=candidate.aggregate_confidence,
                )
            except Exception as exc:  # noqa: BLE001 - sampler/provider boundary
                # A failed stability measurement is missing evidence, not agreement.
                return T2Decision(
                    outcome=T2Outcome.ESCALATE,
                    candidate=candidate,
                    quality_decision=None,
                    reason=f"self_consistency_error:{type(exc).__name__}",
                )
            if cascade.result is not None:
                # A measurement may only preserve or lower autonomy. The aggregate is a
                # mean, so merging a stability at or above the current confidence would
                # RAISE it; that measurement is recorded as a hold decision only.
                stability = cascade.result.stability
                if stability < candidate.aggregate_confidence:
                    candidate = replace(
                        candidate,
                        confidence_signals={
                            **candidate.confidence_signals,
                            **cascade.result.signal,
                        },
                    )
            stability_hold = cascade.stable is False
        try:
            decision = await self._quality_gate.evaluate(candidate)
        except Exception as exc:  # noqa: BLE001 - gate dependency boundary
            return T2Decision(
                outcome=T2Outcome.ESCALATE,
                candidate=candidate,
                quality_decision=None,
                reason=f"quality_gate_error:{type(exc).__name__}",
            )
        outcome = _OUTCOME_MAP[decision.outcome]
        reason = (
            "quality_gate_eligible"
            if outcome is T2Outcome.PROPOSED
            else f"quality_gate_{decision.outcome.value}"
        )
        if stability_hold and outcome is not T2Outcome.DENIED:
            # Subtractive hold: an unstable proposer never grants eligibility. A gate
            # deny stays denied, and the quality decision remains attached either way so
            # the audit record keeps the measured stability and the gate's own reasons.
            outcome = T2Outcome.ESCALATE
            reason = "self_consistency_unstable"
        return T2Decision(
            outcome=outcome,
            candidate=candidate,
            quality_decision=decision,
            reason=reason,
        )


__all__ = [
    "QualityGateProtocol",
    "T2Decision",
    "T2Outcome",
    "T2ProposalContext",
    "T2Proposer",
    "T2Tier",
]
