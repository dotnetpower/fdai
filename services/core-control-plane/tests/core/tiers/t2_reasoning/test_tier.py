"""T2Tier - propose + quality-gate, outcome mapping and real-gate integration.

The mapping matrix (gate outcome -> tier outcome) is exercised with a trivial
fake gate; one integration test drives a real QualityGate wired with the
quality-gate testing fakes to prove the composition holds. Async tests run
under asyncio_mode="auto".
"""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest
from fdai.core.metering.budget import InMemoryBudgetLedger, ModelBudget
from fdai.core.quality_gate._audit import quality_decision_audit_fields
from fdai.core.quality_gate.escalation_ladder import EscalationLadderConfig
from fdai.core.quality_gate.gate import (
    QualityCandidate,
    QualityDecision,
    QualityGate,
    QualityOutcome,
)
from fdai.core.quality_gate.self_consistency import (
    STABILITY_SIGNAL_KEY,
    SelfConsistencyCascade,
    SelfConsistencySampler,
)
from fdai.core.quality_gate.testing import (
    MatchTypeCrossCheckModel,
    MismatchCrossCheckModel,
    SequenceCrossCheckModel,
    StaticVerifier,
)
from fdai.core.tiers.t2_reasoning import T2Outcome, T2ProposalContext, T2Tier
from fdai.shared.contracts.models import Event, Mode, Rule


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


def _rule(
    *,
    rule_id: str = "r1",
    remediates: str = "remediate.tag-add",
    alternatives: tuple[str, ...] = (),
) -> Rule:
    payload = {
        "schema_version": "1.0.0",
        "id": rule_id,
        "version": "1.0.0",
        "source": "custom",
        "severity": "low",
        "category": "config_drift",
        "resource_type": "compute.vm",
        "check_logic": {"kind": "rego", "reference": "policies/example.rego"},
        "remediation": {"template_ref": "remediations/example"},
        "remediates": remediates,
        "provenance": {
            "source_url": f"https://example.com/rules/{rule_id}",
            "resolved_ref": "0000000000000000000000000000000000000000",
            "content_hash": "sha256:example",
            "license": "MIT",
            "redistribution": "embeddable",
            "retrieved_at": "2026-07-05T00:00:00Z",
        },
    }
    if alternatives:
        payload["alternatives"] = list(alternatives)
    return Rule.model_validate(payload)


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
        allowed_rules=(_rule(),),
    )


class _FakeGate:
    def __init__(self, outcome: QualityOutcome) -> None:
        self._outcome = outcome
        self.calls = 0

    async def evaluate(self, candidate: QualityCandidate) -> QualityDecision:
        self.calls += 1
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


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (
            replace(_candidate(), target_resource_ref="resource:example/rg/other"),
            "target_resource_ref",
        ),
        (
            replace(_candidate(), target_resource_type="storage.account"),
            "target_resource_type",
        ),
        (
            replace(_candidate(), cited_rule_ids=("unrouted-rule",)),
            "cited_rule_not_allowed",
        ),
        (
            replace(_candidate(), action_type="ops.scale-out"),
            "action_type_not_allowed",
        ),
    ],
)
async def test_candidate_must_match_trusted_context(
    candidate: QualityCandidate,
    reason: str,
) -> None:
    gate = _FakeGate(QualityOutcome.ELIGIBLE)
    tier = T2Tier(proposer=_Proposer(candidate), quality_gate=gate)

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.DENIED
    assert decision.reason == f"t2_candidate_context_mismatch:{reason}"
    assert decision.quality_decision is None
    assert gate.calls == 0


async def test_missing_candidate_resource_type_is_bound_from_trusted_context() -> None:
    gate = _FakeGate(QualityOutcome.ELIGIBLE)
    tier = T2Tier(proposer=_Proposer(_candidate()), quality_gate=gate)

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.PROPOSED
    assert decision.candidate is not None
    assert decision.candidate.target_resource_type == "compute.vm"


@pytest.mark.parametrize(
    "allowed_rules",
    [
        (_rule(alternatives=("ops.scale-out",)),),
        (
            _rule(rule_id="r1"),
            _rule(rule_id="r2", remediates="ops.scale-out"),
        ),
    ],
)
async def test_candidate_action_may_be_authorized_by_one_routed_rule(
    allowed_rules: tuple[Rule, ...],
) -> None:
    candidate = replace(
        _candidate(),
        action_type="ops.scale-out",
        cited_rule_ids=tuple(rule.id for rule in allowed_rules),
    )
    gate = _FakeGate(QualityOutcome.ELIGIBLE)
    tier = T2Tier(proposer=_Proposer(candidate), quality_gate=gate)
    context = replace(_context(), allowed_rules=allowed_rules)

    decision = await tier.evaluate(context=context)

    assert decision.outcome is T2Outcome.PROPOSED
    assert gate.calls == 1


async def test_candidate_action_rejects_multiple_authorizing_rules() -> None:
    allowed_rules = (
        _rule(rule_id="r1", remediates="ops.scale-out"),
        _rule(rule_id="r2", alternatives=("ops.scale-out",)),
    )
    candidate = replace(
        _candidate(),
        action_type="ops.scale-out",
        cited_rule_ids=("r1", "r2"),
    )
    gate = _FakeGate(QualityOutcome.ELIGIBLE)
    tier = T2Tier(proposer=_Proposer(candidate), quality_gate=gate)

    decision = await tier.evaluate(context=replace(_context(), allowed_rules=allowed_rules))

    assert decision.outcome is T2Outcome.DENIED
    assert decision.reason == "t2_candidate_context_mismatch:action_type_rule_ambiguous"
    assert gate.calls == 0


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
            allowed_rules=(_rule(),),
        )
        outcomes.append((await tier.evaluate(context=context)).outcome)

    assert outcomes == [T2Outcome.PROPOSED] * 3
    assert proposer.calls == 3


async def test_the_tier_never_carries_a_money_limb_it_cannot_observe() -> None:
    """A ceiling that can never fire reads like one, so it must not exist.

    The proposer meters its own usage straight to the metering sink, so
    no cost ever lands on the tier's ledger. A declared per-correlation
    money limb would therefore sit at zero spend forever while looking
    like an enforced bound.
    """
    proposer = _Proposer(_candidate())
    tier = T2Tier(
        proposer=proposer,
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        # A one-microUSD limb would deny immediately if it were live.
        budget=ModelBudget(
            max_calls_per_correlation=8,
            max_cost_microusd_per_correlation=1,
        ),
    )

    for index in range(4):
        event = _event().model_copy(
            update={"event_id": f"00000000-0000-0000-0000-00000000000{index}"}
        )
        context = T2ProposalContext(
            event=event,
            target_resource_ref="resource:example/rg/x",
            target_resource_type="compute.vm",
            allowed_rules=(_rule(),),
        )
        assert (await tier.evaluate(context=context)).reason != "t2_budget_exhausted"

    assert proposer.calls == 4


# ---------------------------------------------------------------------------
# Self-consistency cascade (hallucination-rubric-gate.md § Self-consistency)
# ---------------------------------------------------------------------------


def _cascade(
    *,
    sequence: tuple[str, ...],
    sample_threshold: float = 1.0,
    stability_threshold: float = 0.7,
) -> tuple[SelfConsistencyCascade, SequenceCrossCheckModel]:
    proposer = SequenceCrossCheckModel(sequence=sequence)
    return (
        SelfConsistencyCascade(
            sampler=SelfConsistencySampler(proposer=proposer, samples=len(sequence)),
            sample_threshold=sample_threshold,
            stability_threshold=stability_threshold,
        ),
        proposer,
    )


def _ladder_gate() -> QualityGate:
    return QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=_Grounding(),
        escalation_ladder_config=EscalationLadderConfig(),
    )


async def test_unstable_cascade_reaches_the_decision_without_granting_eligibility() -> None:
    cascade, _ = _cascade(sequence=("a", "b", "c"))
    tier = T2Tier(
        proposer=_Proposer(_candidate()),
        quality_gate=_ladder_gate(),
        self_consistency=cascade,
    )

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.ESCALATE
    assert decision.reason == "self_consistency_unstable"
    assert decision.eligible_for_risk_gate is False
    assert decision.quality_decision is not None
    assert decision.quality_decision.self_consistency == pytest.approx(1 / 3)
    assert decision.candidate is not None
    assert decision.candidate.confidence_signals[STABILITY_SIGNAL_KEY] == pytest.approx(1 / 3)
    audit = quality_decision_audit_fields(decision.quality_decision)
    assert audit["self_consistency"] == pytest.approx(1 / 3)


async def test_stable_cascade_preserves_eligibility_without_raising_confidence() -> None:
    cascade, _ = _cascade(sequence=("a", "a", "a"))
    candidate = _candidate(confidence={"a": 0.7, "b": 0.8})
    tier = T2Tier(
        proposer=_Proposer(candidate),
        quality_gate=_ladder_gate(),
        self_consistency=cascade,
    )

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.PROPOSED
    assert decision.reason == "quality_gate_eligible"
    assert decision.quality_decision is not None
    # 1.0 is above the 0.75 aggregate, so merging it would raise the mean.
    assert decision.quality_decision.self_consistency is None
    assert decision.quality_decision.aggregate_confidence == pytest.approx(0.75)


async def test_a_subtractive_stability_lowers_the_recorded_confidence() -> None:
    cascade, _ = _cascade(sequence=("a", "a", "b", "b"), stability_threshold=0.4)
    candidate = _candidate(confidence={"a": 0.9, "b": 0.9})
    tier = T2Tier(
        proposer=_Proposer(candidate),
        quality_gate=_ladder_gate(),
        self_consistency=cascade,
    )

    decision = await tier.evaluate(context=_context())

    assert decision.quality_decision is not None
    assert decision.quality_decision.self_consistency == pytest.approx(0.5)
    assert decision.quality_decision.aggregate_confidence == pytest.approx((0.9 + 0.9 + 0.5) / 3)


async def test_a_confident_candidate_spends_no_sampling_calls() -> None:
    cascade, proposer = _cascade(sequence=("a", "b", "c"), sample_threshold=0.0)
    tier = T2Tier(
        proposer=_Proposer(_candidate()),
        quality_gate=_ladder_gate(),
        self_consistency=cascade,
    )

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.PROPOSED
    assert decision.quality_decision is not None
    assert decision.quality_decision.self_consistency is None
    assert proposer._idx == 0


async def test_a_failed_stability_measurement_fails_closed() -> None:
    class _BrokenSampler:
        async def sample(self, candidate: QualityCandidate) -> object:
            del candidate
            raise RuntimeError("sampler down")

    tier = T2Tier(
        proposer=_Proposer(_candidate()),
        quality_gate=_FakeGate(QualityOutcome.ELIGIBLE),
        self_consistency=SelfConsistencyCascade(
            sampler=cast(SelfConsistencySampler, _BrokenSampler()),
            sample_threshold=1.0,
            stability_threshold=0.7,
        ),
    )

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.ESCALATE
    assert decision.reason == "self_consistency_error:RuntimeError"
    assert decision.quality_decision is None


async def test_an_unstable_candidate_cannot_upgrade_a_denied_outcome() -> None:
    cascade, _ = _cascade(sequence=("a", "b"))
    tier = T2Tier(
        proposer=_Proposer(_candidate()),
        quality_gate=_FakeGate(QualityOutcome.DENY),
        self_consistency=cascade,
    )

    decision = await tier.evaluate(context=_context())

    assert decision.outcome is T2Outcome.DENIED
    assert decision.reason == "quality_gate_deny"
