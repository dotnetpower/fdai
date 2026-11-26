"""Self-consistency sampler - stability reduction + sampling.

Design reference: ``docs/roadmap/decisioning/hallucination-rubric-gate.md`` §
Self-consistency.
"""

from __future__ import annotations

import pytest
from fdai.core.quality_gate.critic import (
    CriticObjection,
    CriticOutput,
    CriticSeverity,
    CriticStance,
    CriticVerdict,
    evaluate_critic_output,
)
from fdai.core.quality_gate.debate import (
    DebateOrchestrator,
    DebateOrchestratorConfig,
    DebateVerdict,
)
from fdai.core.quality_gate.debate_router import (
    DebateRoute,
    DebateRouterConfig,
    decide_debate_route,
)
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.judge import (
    JudgeDecision,
    JudgeOutput,
    JudgeVerdict,
    evaluate_judge_output,
)
from fdai.core.quality_gate.self_consistency import (
    STABILITY_SIGNAL_KEY,
    CascadeDecision,
    SelfConsistencySampler,
    compute_stability,
    run_consistency_cascade,
)
from fdai.core.quality_gate.testing import SequenceCrossCheckModel


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={},
        cited_rule_ids=("r.known",),
    )


class TestComputeStability:
    def test_uniform_is_full_stability(self) -> None:
        modal, count, stability = compute_stability(["a", "a", "a"])
        assert modal == "a"
        assert count == 3
        assert stability == pytest.approx(1.0)

    def test_majority(self) -> None:
        modal, count, stability = compute_stability(["a", "a", "b"])
        assert modal == "a"
        assert count == 2
        assert stability == pytest.approx(2 / 3)

    def test_all_distinct_is_low(self) -> None:
        modal, count, stability = compute_stability(["a", "b", "c"])
        assert count == 1
        assert stability == pytest.approx(1 / 3)

    def test_tie_breaks_on_first_seen(self) -> None:
        # a and b both appear twice; first-seen (a) wins for determinism.
        modal, count, stability = compute_stability(["a", "b", "a", "b"])
        assert modal == "a"
        assert count == 2

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            compute_stability([])


class TestSelfConsistencySampler:
    def test_rejects_zero_samples(self) -> None:
        with pytest.raises(ValueError, match="samples MUST be"):
            SelfConsistencySampler(proposer=SequenceCrossCheckModel(sequence=("a",)), samples=0)

    @pytest.mark.asyncio
    async def test_stable_proposer(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("remediate.tag-add",)), samples=4
        )
        result = await sampler.sample(_candidate())
        assert result.total == 4
        assert result.stability == pytest.approx(1.0)
        assert result.modal_action_type == "remediate.tag-add"
        assert result.signal == {STABILITY_SIGNAL_KEY: 1.0}

    @pytest.mark.asyncio
    async def test_unstable_proposer_lowers_stability(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a", "b", "a", "c")), samples=4
        )
        result = await sampler.sample(_candidate())
        assert result.total == 4
        assert result.modal_action_type == "a"
        assert result.agreement_count == 2
        assert result.stability == pytest.approx(0.5)
        assert result.signal[STABILITY_SIGNAL_KEY] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_proposer_failure_propagates(self) -> None:
        class _RaisingProposer:
            async def propose(self, candidate: QualityCandidate) -> tuple[str, dict[str, object]]:
                del candidate
                raise RuntimeError("proposer offline")

        sampler = SelfConsistencySampler(proposer=_RaisingProposer(), samples=3)
        with pytest.raises(RuntimeError, match="proposer offline"):
            await sampler.sample(_candidate())

    @pytest.mark.asyncio
    async def test_sibling_samples_cancelled_on_failure(self) -> None:
        # One sample raises immediately; the siblings would hang. The
        # sampler MUST cancel the in-flight siblings before propagating,
        # so this returns promptly (no 30s wait) and leaks no task.
        import asyncio

        started: list[asyncio.Task[object]] = []

        class _OneRaisesRestHang:
            def __init__(self) -> None:
                self.calls = 0

            async def propose(self, candidate: QualityCandidate) -> tuple[str, dict[str, object]]:
                del candidate
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("boom")
                current = asyncio.current_task()
                if current is not None:
                    started.append(current)
                await asyncio.sleep(30)  # would hang unless cancelled
                return ("x", {})

        sampler = SelfConsistencySampler(proposer=_OneRaisesRestHang(), samples=3)
        with pytest.raises(RuntimeError, match="boom"):
            await sampler.sample(_candidate())
        # Give the event loop a tick to process the cancellations.
        await asyncio.sleep(0)
        assert all(t.cancelled() or t.done() for t in started)


class TestCascade:
    @pytest.mark.asyncio
    async def test_strong_signal_skips_sampling(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a",)), samples=3
        )
        decision = await run_consistency_cascade(
            sampler,
            _candidate(),
            aggregate_confidence=0.9,
            sample_threshold=0.7,
            stability_threshold=0.6,
        )
        assert decision == CascadeDecision(should_sample=False, stable=None, result=None)

    @pytest.mark.asyncio
    async def test_weak_signal_stable(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a",)), samples=4
        )
        decision = await run_consistency_cascade(
            sampler,
            _candidate(),
            aggregate_confidence=0.4,
            sample_threshold=0.7,
            stability_threshold=0.6,
        )
        assert decision.should_sample is True
        assert decision.stable is True
        assert decision.result is not None
        assert decision.result.stability == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_rejects_out_of_range_thresholds(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a",)), samples=2
        )
        with pytest.raises(ValueError, match="sample_threshold"):
            await run_consistency_cascade(
                sampler,
                _candidate(),
                aggregate_confidence=0.5,
                sample_threshold=1.5,
                stability_threshold=0.6,
            )
        with pytest.raises(ValueError, match="stability_threshold"):
            await run_consistency_cascade(
                sampler,
                _candidate(),
                aggregate_confidence=0.5,
                sample_threshold=0.7,
                stability_threshold=-0.1,
            )

    @pytest.mark.asyncio
    async def test_weak_signal_unstable_is_gate_not_dilution(self) -> None:
        # Unstable proposer under a weak cheap signal -> stable is False.
        # The caller routes that to HIL; the low stability is NOT averaged
        # into confidence where a high signal could mask it.
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a", "b", "c", "d")), samples=4
        )
        decision = await run_consistency_cascade(
            sampler,
            _candidate(),
            aggregate_confidence=0.4,
            sample_threshold=0.7,
            stability_threshold=0.6,
        )
        assert decision.should_sample is True
        assert decision.stable is False
        assert decision.result is not None
        assert decision.result.stability == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Critic, Judge, DebateRouter, and DebateOrchestrator unit coverage
# ---------------------------------------------------------------------------


class TestCriticEvaluator:
    def test_objection_validation_rejects_blank_fields(self) -> None:
        with pytest.raises(ValueError, match="cited_rule_id MUST be non-empty"):
            CriticObjection(severity=CriticSeverity.LOW, cited_rule_id="  ", description="valid")
        with pytest.raises(ValueError, match="description MUST be non-empty"):
            CriticObjection(severity=CriticSeverity.LOW, cited_rule_id="r.known", description=" ")

    def test_evaluate_critic_output_all_stances_and_branches(self) -> None:
        known = ("r.known",)
        low_obj = CriticObjection(
            severity=CriticSeverity.LOW, cited_rule_id="r.known", description="minor"
        )
        med_obj = CriticObjection(
            severity=CriticSeverity.MEDIUM, cited_rule_id="r.known", description="medium"
        )
        high_obj = CriticObjection(
            severity=CriticSeverity.HIGH, cited_rule_id="r.known", description="severe"
        )
        unknown_obj = CriticObjection(
            severity=CriticSeverity.MEDIUM, cited_rule_id="r.unknown", description="ungrounded"
        )

        # ABSTAIN short-circuits.
        assert (
            evaluate_critic_output(CriticOutput(stance=CriticStance.ABSTAIN), known_rule_ids=known)
            is CriticVerdict.ABSTAIN
        )
        # AGREE without high severity -> ENDORSE; with high severity -> ABORT.
        assert (
            evaluate_critic_output(
                CriticOutput(stance=CriticStance.AGREE, objections=(low_obj,)),
                known_rule_ids=known,
            )
            is CriticVerdict.ENDORSE
        )
        assert (
            evaluate_critic_output(
                CriticOutput(stance=CriticStance.AGREE, objections=(high_obj,)),
                known_rule_ids=known,
            )
            is CriticVerdict.ABORT
        )
        # CHALLENGE empty -> ABSTAIN; unknown citation -> ABSTAIN; high -> ABORT; medium -> RETRY.
        assert (
            evaluate_critic_output(
                CriticOutput(stance=CriticStance.CHALLENGE, objections=()),
                known_rule_ids=known,
            )
            is CriticVerdict.ABSTAIN
        )
        assert (
            evaluate_critic_output(
                CriticOutput(stance=CriticStance.CHALLENGE, objections=(unknown_obj,)),
                known_rule_ids=known,
            )
            is CriticVerdict.ABSTAIN
        )
        assert (
            evaluate_critic_output(
                CriticOutput(stance=CriticStance.CHALLENGE, objections=(high_obj,)),
                known_rule_ids=known,
            )
            is CriticVerdict.ABORT
        )
        assert (
            evaluate_critic_output(
                CriticOutput(stance=CriticStance.CHALLENGE, objections=(med_obj,)),
                known_rule_ids=known,
            )
            is CriticVerdict.RETRY
        )


class TestJudgeEvaluator:
    def test_judge_output_rejects_blank_justification(self) -> None:
        with pytest.raises(ValueError, match="justification MUST be non-empty"):
            JudgeOutput(decision=JudgeDecision.ACCEPT, justification="   ")

    def test_evaluate_judge_output_all_branches(self) -> None:
        known = ("r.known",)
        # Unknown citation collapses to ESCALATE.
        assert (
            evaluate_judge_output(
                JudgeOutput(
                    decision=JudgeDecision.ACCEPT,
                    justification="ok",
                    citations=("r.unknown",),
                ),
                known_rule_ids=known,
            )
            is JudgeVerdict.ESCALATE
        )
        # ACCEPT with known citation -> PROCEED.
        assert (
            evaluate_judge_output(
                JudgeOutput(
                    decision=JudgeDecision.ACCEPT,
                    justification="ok",
                    citations=("r.known",),
                ),
                known_rule_ids=known,
            )
            is JudgeVerdict.PROCEED
        )
        # REVISE_AND_RETRY without directive or blank directive -> ESCALATE.
        assert (
            evaluate_judge_output(
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="retry needed",
                    retry_directive=None,
                ),
                known_rule_ids=known,
            )
            is JudgeVerdict.ESCALATE
        )
        assert (
            evaluate_judge_output(
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="retry needed",
                    retry_directive="   ",
                ),
                known_rule_ids=known,
            )
            is JudgeVerdict.ESCALATE
        )
        # REVISE_AND_RETRY with non-blank directive -> RETRY.
        assert (
            evaluate_judge_output(
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="retry needed",
                    retry_directive="use safe tag",
                    citations=("r.known",),
                ),
                known_rule_ids=known,
            )
            is JudgeVerdict.RETRY
        )
        # ESCALATE_HIL -> ESCALATE.
        assert (
            evaluate_judge_output(
                JudgeOutput(decision=JudgeDecision.ESCALATE_HIL, justification="unsafe"),
                known_rule_ids=known,
            )
            is JudgeVerdict.ESCALATE
        )


class TestDebateRouter:
    def test_config_rejects_overlapping_allow_and_never_lists(self) -> None:
        with pytest.raises(ValueError, match="disjoint"):
            DebateRouterConfig(
                always_for_action_types=("remediate.tag-add",),
                never_for_action_types=("remediate.tag-add",),
            )

    def test_decide_debate_route_precedence(self) -> None:
        cand = _candidate()
        # 1. orchestrator_available=False -> SKIP
        d1 = decide_debate_route(
            candidate=cand, cross_check_disagreed=True, orchestrator_available=False
        )
        assert d1.route is DebateRoute.SKIP
        assert d1.reason == "orchestrator_unavailable"

        # 2. enabled=False -> SKIP
        d2 = decide_debate_route(
            candidate=cand,
            cross_check_disagreed=True,
            orchestrator_available=True,
            config=DebateRouterConfig(enabled=False),
        )
        assert d2.route is DebateRoute.SKIP
        assert d2.reason == "disabled"

        # 3. never_for_action_types -> SKIP
        d3 = decide_debate_route(
            candidate=cand,
            cross_check_disagreed=True,
            orchestrator_available=True,
            config=DebateRouterConfig(never_for_action_types=("remediate.tag-add",)),
        )
        assert d3.route is DebateRoute.SKIP
        assert d3.reason == "never_list"

        # 4. always_for_action_types -> DEBATE (even without disagreement)
        d4 = decide_debate_route(
            candidate=cand,
            cross_check_disagreed=False,
            orchestrator_available=True,
            config=DebateRouterConfig(always_for_action_types=("remediate.tag-add",)),
        )
        assert d4.route is DebateRoute.DEBATE
        assert d4.reason == "always_list"

        # 5. cross_check_disagreed=True -> DEBATE
        d5 = decide_debate_route(
            candidate=cand, cross_check_disagreed=True, orchestrator_available=True
        )
        assert d5.route is DebateRoute.DEBATE
        assert d5.reason == "cross_check_disagreement"

        # 6. Fallback -> SKIP
        d6 = decide_debate_route(
            candidate=cand, cross_check_disagreed=False, orchestrator_available=True
        )
        assert d6.route is DebateRoute.SKIP
        assert d6.reason == "default_skip"


class _SeqCritic:
    def __init__(self, items: list[CriticOutput | Exception]) -> None:
        self._items = list(items)

    async def critique(self, candidate: QualityCandidate, proposer_output: object) -> CriticOutput:
        del candidate, proposer_output
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _SeqJudge:
    def __init__(self, items: list[JudgeOutput | Exception]) -> None:
        self._items = list(items)

    async def judge(
        self, candidate: QualityCandidate, proposer_output: object, critic_output: CriticOutput
    ) -> JudgeOutput:
        del candidate, proposer_output, critic_output
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestDebateOrchestrator:
    def test_config_rejects_out_of_bounds_max_rounds(self) -> None:
        with pytest.raises(ValueError, match="max_rounds MUST be in"):
            DebateOrchestratorConfig(max_rounds=-1)
        with pytest.raises(ValueError, match="max_rounds MUST be in"):
            DebateOrchestratorConfig(max_rounds=2)

    @pytest.mark.asyncio
    async def test_run_requires_retry_proposer_when_max_rounds_positive(self) -> None:
        orch = DebateOrchestrator(
            critic=_SeqCritic([]),  # type: ignore[arg-type]
            judge=_SeqJudge([]),  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="retry_proposer MUST be supplied"):
            await orch.run(
                candidate=_candidate(),
                proposer_output=("remediate.tag-add", {}),
                known_rule_ids=("r.known",),
                retry_proposer=None,
            )

    @pytest.mark.asyncio
    async def test_round1_errors_and_abstain_paths(self) -> None:
        cand = _candidate()
        prop = ("remediate.tag-add", {})

        async def _noop_retry(c: QualityCandidate, d: str) -> tuple[str, dict[str, object]]:
            del c, d
            return ("remediate.tag-add", {"retried": True})

        # Critic exception in round 1.
        orch_critic_err = DebateOrchestrator(
            critic=_SeqCritic([RuntimeError("critic boom")]),  # type: ignore[arg-type]
            judge=_SeqJudge([]),  # type: ignore[arg-type]
        )
        out1 = await orch_critic_err.run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_noop_retry,
        )
        assert out1.verdict is DebateVerdict.ABORT
        assert out1.error_class == "RuntimeError"
        assert "critic model error" in out1.reason

        # Critic ABSTAIN in round 1.
        orch_critic_abstain = DebateOrchestrator(
            critic=_SeqCritic([CriticOutput(stance=CriticStance.ABSTAIN)]),  # type: ignore[arg-type]
            judge=_SeqJudge([]),  # type: ignore[arg-type]
        )
        out2 = await orch_critic_abstain.run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_noop_retry,
        )
        assert out2.verdict is DebateVerdict.ABORT
        assert out2.critic_verdict is CriticVerdict.ABSTAIN

        # Judge exception in round 1.
        orch_judge_err = DebateOrchestrator(
            critic=_SeqCritic([CriticOutput(stance=CriticStance.AGREE)]),  # type: ignore[arg-type]
            judge=_SeqJudge([RuntimeError("judge boom")]),  # type: ignore[arg-type]
        )
        out3 = await orch_judge_err.run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_noop_retry,
        )
        assert out3.verdict is DebateVerdict.ABORT
        assert out3.error_class == "RuntimeError"
        assert "judge model error" in out3.reason

        # Judge RETRY when max_rounds=0 forbids retry.
        retry_judge_output = JudgeOutput(
            decision=JudgeDecision.REVISE_AND_RETRY,
            justification="tighten scope",
            retry_directive="add scope filter",
            citations=("r.known",),
        )
        orch_zero_rounds = DebateOrchestrator(
            critic=_SeqCritic([CriticOutput(stance=CriticStance.AGREE)]),  # type: ignore[arg-type]
            judge=_SeqJudge([retry_judge_output]),  # type: ignore[arg-type]
            config=DebateOrchestratorConfig(max_rounds=0),
        )
        out4 = await orch_zero_rounds.run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=None,
        )
        assert out4.verdict is DebateVerdict.ABORT
        assert "max_rounds=0 forbids it" in out4.reason

    @pytest.mark.asyncio
    async def test_round2_retry_branches(self) -> None:
        cand = _candidate()
        prop = ("remediate.tag-add", {})
        agree_critic = CriticOutput(stance=CriticStance.AGREE)
        retry_judge = JudgeOutput(
            decision=JudgeDecision.REVISE_AND_RETRY,
            justification="needs revision",
            retry_directive="revise tag",
            citations=("r.known",),
        )
        accept_judge = JudgeOutput(
            decision=JudgeDecision.ACCEPT,
            justification="accepted on retry",
            citations=("r.known",),
        )
        escalate_judge = JudgeOutput(
            decision=JudgeDecision.ESCALATE_HIL,
            justification="still unsafe",
            citations=("r.known",),
        )

        async def _ok_retry(c: QualityCandidate, directive: str) -> tuple[str, dict[str, object]]:
            del c
            return ("remediate.tag-add", {"directive": directive})

        async def _err_retry(c: QualityCandidate, directive: str) -> tuple[str, dict[str, object]]:
            del c, directive
            raise RuntimeError("proposer retry failed")

        # 1. Proposer retry raises exception.
        o1 = await DebateOrchestrator(
            critic=_SeqCritic([agree_critic]),  # type: ignore[arg-type]
            judge=_SeqJudge([retry_judge]),  # type: ignore[arg-type]
        ).run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_err_retry,
        )
        assert o1.verdict is DebateVerdict.ABORT
        assert "proposer retry error" in o1.reason
        assert o1.rounds == 1

        # 2. Critic raises exception on round 2.
        o2 = await DebateOrchestrator(
            critic=_SeqCritic([agree_critic, RuntimeError("critic r2 boom")]),  # type: ignore[arg-type]
            judge=_SeqJudge([retry_judge]),  # type: ignore[arg-type]
        ).run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_ok_retry,
        )
        assert o2.verdict is DebateVerdict.ABORT
        assert "critic model error on retry" in o2.reason
        assert o2.rounds == 2

        # 3. Critic ABSTAIN on round 2.
        o3 = await DebateOrchestrator(
            critic=_SeqCritic([agree_critic, CriticOutput(stance=CriticStance.ABSTAIN)]),  # type: ignore[arg-type]
            judge=_SeqJudge([retry_judge]),  # type: ignore[arg-type]
        ).run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_ok_retry,
        )
        assert o3.verdict is DebateVerdict.ABORT
        assert o3.reason == "critic abstain on retry"
        assert o3.rounds == 2

        # 4. Judge raises exception on round 2.
        o4 = await DebateOrchestrator(
            critic=_SeqCritic([agree_critic, agree_critic]),  # type: ignore[arg-type]
            judge=_SeqJudge([retry_judge, RuntimeError("judge r2 boom")]),  # type: ignore[arg-type]
        ).run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_ok_retry,
        )
        assert o4.verdict is DebateVerdict.ABORT
        assert "judge model error on retry" in o4.reason
        assert o4.rounds == 2

        # 5. Judge PROCEED on round 2.
        o5 = await DebateOrchestrator(
            critic=_SeqCritic([agree_critic, agree_critic]),  # type: ignore[arg-type]
            judge=_SeqJudge([retry_judge, accept_judge]),  # type: ignore[arg-type]
        ).run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_ok_retry,
        )
        assert o5.verdict is DebateVerdict.PROCEED
        assert o5.reason == "judge accepted on retry"
        assert o5.final_proposer_output == ("remediate.tag-add", {"directive": "revise tag"})
        assert o5.rounds == 2

        # 6. Judge ESCALATE on round 2 (max_rounds exhausted).
        o6 = await DebateOrchestrator(
            critic=_SeqCritic([agree_critic, agree_critic]),  # type: ignore[arg-type]
            judge=_SeqJudge([retry_judge, escalate_judge]),  # type: ignore[arg-type]
        ).run(
            candidate=cand,
            proposer_output=prop,
            known_rule_ids=("r.known",),
            retry_proposer=_ok_retry,
        )
        assert o6.verdict is DebateVerdict.ABORT
        assert "max_rounds exhausted" in o6.reason
        assert o6.rounds == 2
