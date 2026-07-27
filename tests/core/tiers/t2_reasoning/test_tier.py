"""T2Tier - propose + quality-gate, outcome mapping and real-gate integration.

The mapping matrix (gate outcome -> tier outcome) is exercised with a trivial
fake gate; one integration test drives a real QualityGate wired with the
quality-gate testing fakes to prove the composition holds. Async tests run
under asyncio_mode="auto".
"""

from __future__ import annotations

import pytest

from fdai.core.metering.budget import InMemoryBudgetLedger, ModelBudget
from fdai.core.quality_gate.gate import (
    QualityCandidate,
    QualityDecision,
    QualityGate,
    QualityOutcome,
)
from fdai.core.quality_gate.testing import (
    MatchTypeCrossCheckModel,
    MismatchCrossCheckModel,
    StaticVerifier,
)
from fdai.core.tiers.t2_reasoning import T2Outcome, T2ProposalContext, T2Tier
from fdai.shared.contracts.models import Event, Mode


def _event() -> Event:
    return Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000042",  # type: ignore[arg-type]
        idempotency_key="t2-evt",
        source="example_detector",
        event_type="novel_anomaly",
        detected_at="2026-07-09T12:00:00Z",  # type: ignore[arg-type]
        ingested_at="2026-07-09T12:00:01Z",  # type: ignore[arg-type]
        mode=Mode.SHADOW,
    )


def _candidate(*, confidence: dict[str, float] | None = None) -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag": "owner"},
        cited_rule_ids=("r1",),
        confidence_signals=confidence if confidence is not None else {"a": 0.8, "b": 0.9},
    )


class _Proposer:
    def __init__(self, candidate: QualityCandidate | None) -> None:
        self._candidate = candidate
        self.calls = 0

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        del context
        self.calls += 1
        return self._candidate


def _context() -> T2ProposalContext:
    return T2ProposalContext(
        event=_event(),
        target_resource_ref="resource:example/rg/x",
        target_resource_type="compute.vm",
        allowed_rules=(),
    )


class _FakeGate:
    def __init__(self, outcome: QualityOutcome) -> None:
        self._outcome = outcome

    async def evaluate(self, candidate: QualityCandidate) -> QualityDecision:
        return QualityDecision(outcome=self._outcome, candidate=candidate)


class _Grounding:
    """Minimal GroundingSource: r1 exists, no topical `supports` hook."""

    def known_rule_ids(self) -> set[str]:
        return {"r1"}

    def get(self, rule_id: str):  # noqa: ANN201 - Protocol conformance
        del rule_id
        return None


# ---------------------------------------------------------------------------
# Outcome mapping (fake gate)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate_outcome", "expected"),
    [
        (QualityOutcome.ELIGIBLE, T2Outcome.PROPOSED),
        (QualityOutcome.ABSTAIN, T2Outcome.ESCALATE),
        (QualityOutcome.DISAGREE, T2Outcome.ESCALATE),
        (QualityOutcome.DENY, T2Outcome.DENIED),
    ],
)
async def test_gate_outcome_maps_to_tier_outcome(
    gate_outcome: QualityOutcome, expected: T2Outcome
) -> None:
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=_FakeGate(gate_outcome))
    decision = await tier.evaluate(context=_context())
    assert decision.outcome is expected
    assert decision.candidate is not None
    assert decision.quality_decision is not None
    assert decision.eligible_for_risk_gate is (expected is T2Outcome.PROPOSED)


async def test_proposer_abstain_yields_tier_abstain() -> None:
    tier = T2Tier(proposer=_Proposer(None), quality_gate=_FakeGate(QualityOutcome.ELIGIBLE))
    decision = await tier.evaluate(context=_context())
    assert decision.outcome is T2Outcome.ABSTAIN
    assert decision.candidate is None
    assert decision.quality_decision is None
    assert decision.reason == "t2_proposer_abstained"
    assert decision.eligible_for_risk_gate is False


# ---------------------------------------------------------------------------
# Real QualityGate integration
# ---------------------------------------------------------------------------


async def test_real_gate_eligible_path_proposes() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=_Grounding(),
    )
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=gate)
    decision = await tier.evaluate(context=_context())
    assert decision.outcome is T2Outcome.PROPOSED
    assert decision.reason == "quality_gate_eligible"


async def test_real_gate_denies_when_verifier_rejects() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=False),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=_Grounding(),
    )
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=gate)
    decision = await tier.evaluate(context=_context())
    assert decision.outcome is T2Outcome.DENIED


async def test_real_gate_escalates_on_cross_check_disagreement() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MismatchCrossCheckModel(model_id="m2"),
        ),
        grounding=_Grounding(),
    )
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=gate)
    decision = await tier.evaluate(context=_context())
    assert decision.outcome is T2Outcome.ESCALATE


async def test_real_gate_escalates_on_low_confidence() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=_Grounding(),
    )
    tier = T2Tier(proposer=_Proposer(_candidate(confidence={"a": 0.2})), quality_gate=gate)
    decision = await tier.evaluate(context=_context())
    assert decision.outcome is T2Outcome.ESCALATE


# ---------------------------------------------------------------------------
# Declared model ceiling (cost-model.md: overflow degrades to a human)
# ---------------------------------------------------------------------------


async def test_a_spent_budget_escalates_instead_of_reasoning_past_the_ceiling() -> None:
    """Overflow degrades to HIL, never to uncapped inference."""
    proposer = _Proposer(_candidate())
    tier = T2Tier(
        proposer=proposer,
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        budget=ModelBudget(max_calls_per_correlation=1, max_calls_total=4),
    )

    first = await tier.evaluate(context=_context())
    second = await tier.evaluate(context=_context())

    assert first.outcome is T2Outcome.PROPOSED
    assert second.outcome is T2Outcome.ESCALATE
    assert second.reason == "t2_budget_exhausted"
    assert second.candidate is None
    # The ceiling held: the model was consulted once, not twice.
    assert proposer.calls == 1


async def test_a_zero_budget_never_reaches_the_proposer() -> None:
    proposer = _Proposer(_candidate())
    tier = T2Tier(
        proposer=proposer,
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        budget=ModelBudget(max_calls_per_correlation=0, max_calls_total=0),
    )

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.ESCALATE
    assert decision.reason == "t2_budget_exhausted"
    assert proposer.calls == 0


async def test_a_failing_proposer_still_consumed_the_budget_it_was_granted() -> None:
    """A failing provider MUST NOT be retriable without limit."""

    class _BrokenProposer:
        calls = 0

        async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
            self.calls += 1
            raise RuntimeError("provider down")

    proposer = _BrokenProposer()
    tier = T2Tier(
        proposer=proposer,
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        budget=ModelBudget(max_calls_per_correlation=1, max_calls_total=4),
    )

    first = await tier.evaluate(context=_context())
    second = await tier.evaluate(context=_context())

    assert first.reason.startswith("t2_proposer_error")
    assert second.reason == "t2_budget_exhausted"
    assert proposer.calls == 1


async def test_a_shared_ledger_bounds_every_tier_that_binds_it() -> None:
    """One declared ceiling, not one per construction site."""
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=1, max_calls_total=1))
    first_tier = T2Tier(
        proposer=_Proposer(_candidate()),
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        budget_ledger=ledger,
    )
    second_tier = T2Tier(
        proposer=_Proposer(_candidate()),
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        budget_ledger=ledger,
    )

    assert (await first_tier.evaluate(context=_context())).outcome is T2Outcome.PROPOSED
    assert (await second_tier.evaluate(context=_context())).reason == "t2_budget_exhausted"


async def test_every_event_of_one_incident_still_reaches_the_proposer() -> None:
    """A correlation id is shared by a storm; the unit of work is the event."""
    proposer = _Proposer(_candidate())
    tier = T2Tier(
        proposer=proposer,
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        budget=ModelBudget(max_calls_per_correlation=1),
    )
    incident = "00000000-0000-0000-0000-0000000000aa"

    outcomes = []
    for index in range(3):
        event = _event().model_copy(
            update={
                "event_id": f"00000000-0000-0000-0000-00000000000{index}",
                "correlation_id": incident,
            }
        )
        context = T2ProposalContext(
            event=event,
            target_resource_ref="resource:example/rg/x",
            target_resource_type="compute.vm",
            allowed_rules=(),
        )
        outcomes.append((await tier.evaluate(context=context)).outcome)

    assert outcomes == [T2Outcome.PROPOSED] * 3
    assert proposer.calls == 3
