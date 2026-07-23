"""QualityGate - outcome + property invariants."""

from __future__ import annotations

import asyncio

import pytest

from fdai.core.quality_gate import (
    QualityCandidate,
    QualityDecision,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
)
from fdai.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    MismatchCrossCheckModel,
    StaticVerifier,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)


def _rule(rule_id: str) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="object-storage",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _candidate(
    *,
    action_type: str = "remediate.tag-add",
    cited: tuple[str, ...] = ("r.known",),
    confidence: dict[str, float] | None = None,
) -> QualityCandidate:
    signals: dict[str, float] = (
        {"retrieval": 0.9, "verifier_margin": 0.9} if confidence is None else confidence
    )
    return QualityCandidate(
        action_type=action_type,
        target_resource_ref="rid-1",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=cited,
        confidence_signals=signals,
    )


def _grounding(rule_ids: tuple[str, ...] = ("r.known",)) -> InMemoryGroundingSource:
    return InMemoryGroundingSource({rid: _rule(rid) for rid in rule_ids})


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_out_of_range_confidence_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="confidence_threshold"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(confidence_threshold=1.5),
        )


def test_zero_quorum_is_rejected() -> None:
    with pytest.raises(ValueError, match="require_cross_check_quorum"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(require_cross_check_quorum=0),
        )


def test_quorum_larger_than_models_is_rejected() -> None:
    with pytest.raises(ValueError, match="not enough cross-check models"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(require_cross_check_quorum=3),
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eligible_when_all_gates_pass() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.reasons == ()
    assert decision.grounded_rule_ids == ("r.known",)
    assert decision.aggregate_confidence > 0.7


@pytest.mark.asyncio
async def test_prompt_evidence_is_optional_on_votes_and_serialized_when_present() -> None:
    from fdai.core.prompts import (
        ComposedPrompt,
        LayerRef,
        PromptLayer,
        SkillReplayRecord,
        SkillSelectionStatus,
    )
    from fdai.core.quality_gate import CrossCheckProposal, quality_decision_audit_fields

    composed = ComposedPrompt(
        system_text="evidence prompt",
        layer_manifest=(LayerRef(id="base", version=1, layer=PromptLayer.BASE, token_estimate=4),),
        token_estimate=4,
        skill_records=(
            SkillReplayRecord(
                operation="load_skill",
                name="inventory-evidence",
                version="1.2.3",
                raw_markdown_sha256="a" * 64,
                body_sha256="b" * 64,
                reference_path=None,
                reference_sha256=None,
                status=SkillSelectionStatus.SELECTED,
            ),
        ),
    )
    replay = composed.replay_manifest()

    class _EvidenceModel:
        model_id = "evidence-aware"

        async def propose(self, candidate: QualityCandidate):
            return candidate.action_type, dict(candidate.params)

        async def propose_with_evidence(self, candidate: QualityCandidate):
            return CrossCheckProposal(
                action_type=candidate.action_type,
                params=dict(candidate.params),
                prompt_replay_manifest=replay,
            )

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(_EvidenceModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )

    decision = await gate.evaluate(_candidate())
    fields = quality_decision_audit_fields(decision)

    assert decision.model_votes[0].prompt_replay_manifest == replay
    assert decision.model_votes[1].prompt_replay_manifest is None
    evidence_fields = fields["model_votes"][0]["prompt_replay_manifest"]
    assert evidence_fields["system_text_sha256"] == replay.system_text_sha256
    assert evidence_fields["skill_records"][0]["body_sha256"] == "b" * 64
    assert "prompt_replay_manifest" not in fields["model_votes"][1]


# ---------------------------------------------------------------------------
# Verifier paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_deny_short_circuits() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=False),  # explicit deny
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DENY
    assert decision.reasons == ("verifier_rejected",)


@pytest.mark.asyncio
async def test_verifier_abstain_is_recorded_but_not_fatal_alone() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=None),  # abstain
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    # Abstain alone shifts outcome to ABSTAIN (a reason is recorded).
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert "verifier_abstained" in decision.reasons


# ---------------------------------------------------------------------------
# Grounding paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_cited_rule_flags_and_may_still_pass_when_others_ground() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(("r.known",)),
    )
    decision = await gate.evaluate(_candidate(cited=("r.known", "r.made-up")))
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert any("unknown_cited_rule:r.made-up" in r for r in decision.reasons)
    assert "r.known" in decision.grounded_rule_ids


@pytest.mark.asyncio
async def test_no_grounded_citation_when_require_grounding_true() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(("r.known",)),
    )
    decision = await gate.evaluate(_candidate(cited=("r.other",)))
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert "no_grounded_citation" in decision.reasons


@pytest.mark.asyncio
async def test_grounding_disabled_does_not_require_citations() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(("r.known",)),
        config=QualityGateConfig(require_grounding=False),
    )
    decision = await gate.evaluate(_candidate(cited=()))
    assert decision.outcome is QualityOutcome.ELIGIBLE


# ---------------------------------------------------------------------------
# Cross-check paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_check_disagreement_below_quorum_becomes_disagree() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE
    assert any("cross_check_below_quorum" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_cross_check_failure_cancels_and_drains_sibling_models() -> None:
    from fdai.core.quality_gate._verification import cross_check_candidate

    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()

    class _FailingModel:
        async def propose(self, candidate: QualityCandidate):
            await sibling_started.wait()
            raise RuntimeError("cross-check unavailable")

    class _BlockingModel:
        async def propose(self, candidate: QualityCandidate):
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sibling_cancelled.set()
                raise

    with pytest.raises(RuntimeError, match="cross-check unavailable"):
        await cross_check_candidate(_candidate(), (_FailingModel(), _BlockingModel()))

    assert sibling_cancelled.is_set()


@pytest.mark.asyncio
async def test_cross_check_agreement_below_quorum_still_disagrees() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE


@pytest.mark.asyncio
async def test_cross_check_exception_fails_closed_to_disagree() -> None:
    """A cross-check model failure must fail closed, never crash the gate."""

    class _RaisingModel:
        async def propose(self, candidate: QualityCandidate):
            raise RuntimeError("cross-check transport down")

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(_RaisingModel(),),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=1),
    )
    decision = await gate.evaluate(_candidate())
    # The gate MUST NOT propagate the exception; the failure is treated as
    # zero agreement (below quorum) so the disagreement path governs the
    # outcome instead of failing open into an eligible result.
    assert decision.outcome is QualityOutcome.DISAGREE
    assert any("cross_check_failed:RuntimeError" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# Escalation ladder (shadow observation)
# ---------------------------------------------------------------------------


def _disagree_gate(**kw: object) -> QualityGate:
    return QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MismatchCrossCheckModel()),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
        **kw,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_escalation_shadow_records_escalate_on_disagreement() -> None:
    from fdai.core.quality_gate import EscalationLadderConfig

    gate = _disagree_gate(
        escalation_ladder_config=EscalationLadderConfig(),
        escalated_available=True,
    )
    decision = await gate.evaluate(_candidate())
    # Outcome is UNCHANGED by the shadow ladder - still a disagreement.
    assert decision.outcome is QualityOutcome.DISAGREE
    assert decision.escalation_route == "escalate"
    assert decision.escalation_reason == "cross_check_disagreement"
    # Shadow MUST NOT leak into reasons (that would flip the outcome).
    assert not any(r.startswith("escalation") for r in decision.reasons)


@pytest.mark.asyncio
async def test_escalation_shadow_fail_closed_when_model_unavailable() -> None:
    from fdai.core.quality_gate import EscalationLadderConfig

    gate = _disagree_gate(
        escalation_ladder_config=EscalationLadderConfig(),
        escalated_available=False,
    )
    decision = await gate.evaluate(_candidate())
    assert decision.escalation_route == "stop"
    assert decision.escalation_reason == "escalated_model_unavailable"


@pytest.mark.asyncio
async def test_escalation_not_recorded_when_ladder_not_wired() -> None:
    gate = _disagree_gate()
    decision = await gate.evaluate(_candidate())
    assert decision.escalation_route is None
    assert decision.escalation_reason is None


@pytest.mark.asyncio
async def test_escalation_audit_fields_present_only_when_wired() -> None:
    from fdai.core.quality_gate import EscalationLadderConfig, quality_decision_audit_fields

    wired = _disagree_gate(
        escalation_ladder_config=EscalationLadderConfig(), escalated_available=True
    )
    d1 = await wired.evaluate(_candidate())
    fields1 = quality_decision_audit_fields(d1)
    assert fields1["escalation_route"] == "escalate"
    assert fields1["escalation_reason"] == "cross_check_disagreement"

    unwired = _disagree_gate()
    d2 = await unwired.evaluate(_candidate())
    fields2 = quality_decision_audit_fields(d2)
    assert "escalation_route" not in fields2


@pytest.mark.asyncio
async def test_escalation_low_self_consistency_trigger_on_agreement() -> None:
    """Both models AGREE, but the proposer is unstable (low action_stability
    from the composition cascade): the ladder escalates on the secondary
    trigger, and the decision records the stability it read."""
    from fdai.core.quality_gate import EscalationLadderConfig

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
        escalation_ladder_config=EscalationLadderConfig(on_self_consistency_below=0.6),
        escalated_available=True,
    )
    candidate = _candidate(
        confidence={"retrieval": 0.9, "verifier_margin": 0.9, "action_stability": 0.4}
    )
    decision = await gate.evaluate(candidate)
    # Agreement -> not a disagreement outcome; shadow escalation does not flip it.
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.self_consistency == 0.4
    assert decision.escalation_route == "escalate"
    assert decision.escalation_reason == "low_self_consistency"


@pytest.mark.asyncio
async def test_escalation_high_self_consistency_does_not_trigger() -> None:
    from fdai.core.quality_gate import EscalationLadderConfig

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
        escalation_ladder_config=EscalationLadderConfig(on_self_consistency_below=0.6),
        escalated_available=True,
    )
    candidate = _candidate(
        confidence={"retrieval": 0.9, "verifier_margin": 0.9, "action_stability": 0.95}
    )
    decision = await gate.evaluate(candidate)
    assert decision.self_consistency == 0.95
    assert decision.escalation_route == "stop"
    assert decision.escalation_reason == "default_stop"


# ---------------------------------------------------------------------------
# Confidence threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_confidence_abstains_even_when_other_gates_pass() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(
        _candidate(confidence={"retrieval": 0.3, "verifier_margin": 0.3})
    )
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert any("confidence=0.30" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_aggregate_confidence_zero_when_no_signals() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate(confidence={}))
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.aggregate_confidence == 0.0


def test_candidate_aggregate_fails_closed_on_non_numeric_signals() -> None:
    candidate = QualityCandidate(
        action_type="a",
        target_resource_ref="r",
        params={},
        cited_rule_ids=(),
        confidence_signals={"good": 0.8, "bad": "not-a-number"},  # type: ignore[dict-item]
    )
    assert candidate.aggregate_confidence == 0.0


def test_candidate_aggregate_fails_closed_on_bool_values() -> None:
    """A bool is malformed confidence evidence, so the whole aggregate is 0."""
    candidate = QualityCandidate(
        action_type="a",
        target_resource_ref="r",
        params={},
        cited_rule_ids=(),
        confidence_signals={"passed": True, "score": 0.6},
    )
    assert candidate.aggregate_confidence == 0.0


def test_candidate_aggregate_bool_only_returns_zero() -> None:
    candidate = QualityCandidate(
        action_type="a",
        target_resource_ref="r",
        params={},
        cited_rule_ids=(),
        confidence_signals={"passed": True, "failed": False},
    )
    assert candidate.aggregate_confidence == 0.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_decision_is_immutable() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    assert isinstance(decision, QualityDecision)
    with pytest.raises((AttributeError, TypeError)):
        decision.outcome = QualityOutcome.DENY  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Wave 4.5 delta-2b: debate escalation on cross-check disagreement
# ---------------------------------------------------------------------------


class _StubCritic:
    """Deterministic Critic stub for QualityGate integration tests.

    Returns AGREE by default so the Judge sees no objection to
    contradict itself with; the specific stance can be tweaked by the
    caller when they need to exercise a different orchestrator branch.
    """

    def __init__(self, stance: str = "agree") -> None:
        from fdai.core.quality_gate.critic import (
            CriticObjection,
            CriticOutput,
            CriticSeverity,
            CriticStance,
        )

        if stance == "agree":
            self._output = CriticOutput(stance=CriticStance.AGREE)
        elif stance == "abort":
            self._output = CriticOutput(
                stance=CriticStance.CHALLENGE,
                objections=(
                    CriticObjection(
                        severity=CriticSeverity.HIGH,
                        cited_rule_id="r.known",
                        description="hard stop",
                    ),
                ),
            )
        else:
            raise ValueError(f"unknown stance {stance!r}")

    async def critique(self, candidate, proposer_output):  # noqa: ANN001,ANN201
        return self._output


class _StubJudge:
    """Deterministic Judge stub. Default: ACCEPT (grounded)."""

    def __init__(self, decision: str = "accept") -> None:
        from fdai.core.quality_gate.judge import JudgeDecision, JudgeOutput

        if decision == "accept":
            self._output = JudgeOutput(
                decision=JudgeDecision.ACCEPT,
                justification="looks good",
                citations=("r.known",),
            )
        elif decision == "escalate_hil":
            self._output = JudgeOutput(
                decision=JudgeDecision.ESCALATE_HIL,
                justification="too risky",
            )
        else:
            raise ValueError(f"unknown decision {decision!r}")

    async def judge(self, candidate, proposer_output, critic_output):  # noqa: ANN001,ANN201
        return self._output


def _build_debate(critic_stance: str = "agree", judge_decision: str = "accept"):
    from fdai.core.quality_gate.debate import (
        DebateOrchestrator,
        DebateOrchestratorConfig,
    )

    return DebateOrchestrator(
        critic=_StubCritic(critic_stance),  # type: ignore[arg-type]
        judge=_StubJudge(judge_decision),  # type: ignore[arg-type]
        config=DebateOrchestratorConfig(max_rounds=1),
    )


def test_gate_rejects_half_wired_debate_orchestrator_missing_router() -> None:
    with pytest.raises(ValueError, match="together"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(require_cross_check_quorum=1),
            debate_orchestrator=_build_debate(),
            debate_router_config=None,
        )


def test_gate_rejects_half_wired_router_config_missing_orchestrator() -> None:
    from fdai.core.quality_gate.debate_router import DebateRouterConfig

    with pytest.raises(ValueError, match="together"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(require_cross_check_quorum=1),
            debate_orchestrator=None,
            debate_router_config=DebateRouterConfig(),
        )


@pytest.mark.asyncio
async def test_debate_proceed_keeps_disagreement_for_human_review() -> None:
    from fdai.core.quality_gate.debate_router import DebateRouterConfig

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
        debate_orchestrator=_build_debate("agree", "accept"),
        debate_router_config=DebateRouterConfig(),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE
    # Debate enriches the audit but cannot override mixed-model disagreement.
    assert any("cross_check_below_quorum" in r for r in decision.reasons)
    assert any("debate_route:debate:cross_check_disagreement" in r for r in decision.reasons)
    assert any("debate_outcome:proceed:judge accepted" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_debate_abort_keeps_disagreement_outcome() -> None:
    from fdai.core.quality_gate.debate_router import DebateRouterConfig

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
        debate_orchestrator=_build_debate("abort", "accept"),  # critic aborts
        debate_router_config=DebateRouterConfig(),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE
    assert any("debate_outcome:abort:critic aborted" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_debate_router_skip_leaves_outcome_as_disagree() -> None:
    """When the router turns off debate (killswitch), disagreement
    stays DISAGREE; no orchestrator call is recorded."""

    from fdai.core.quality_gate.debate_router import DebateRouterConfig

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
        debate_orchestrator=_build_debate(),
        debate_router_config=DebateRouterConfig(enabled=False),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE
    assert any("debate_route:skip:disabled" in r for r in decision.reasons)
    # No debate_outcome reason - the orchestrator was never called.
    assert not any(r.startswith("debate_outcome:") for r in decision.reasons)


@pytest.mark.asyncio
async def test_debate_proceed_with_other_soft_issue_stays_disagree() -> None:
    """Quorum disagreement remains authoritative even with low confidence."""

    from fdai.core.quality_gate.debate_router import DebateRouterConfig

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2, confidence_threshold=0.99),
        debate_orchestrator=_build_debate("agree", "accept"),
        debate_router_config=DebateRouterConfig(),
    )
    # Low-confidence candidate.
    decision = await gate.evaluate(
        _candidate(confidence={"retrieval": 0.1, "verifier_margin": 0.1})
    )
    assert decision.outcome is QualityOutcome.DISAGREE
    assert any("debate_outcome:proceed" in r for r in decision.reasons)
    assert any(r.startswith("confidence=") for r in decision.reasons)


@pytest.mark.asyncio
async def test_debate_judge_escalate_hil_keeps_disagreement() -> None:
    from fdai.core.quality_gate.debate_router import DebateRouterConfig

    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
        debate_orchestrator=_build_debate("agree", "escalate_hil"),
        debate_router_config=DebateRouterConfig(),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE
    assert any("debate_outcome:abort:judge escalated" in r for r in decision.reasons)
