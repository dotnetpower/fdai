"""Unit tests for :mod:`aiopspilot.core.quality_gate.debate`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from aiopspilot.core.quality_gate.critic import (
    CriticObjection,
    CriticOutput,
    CriticSeverity,
    CriticStance,
)
from aiopspilot.core.quality_gate.debate import (
    DebateOrchestrator,
    DebateOrchestratorConfig,
    DebateOutcome,
    DebateVerdict,
)
from aiopspilot.core.quality_gate.gate import QualityCandidate
from aiopspilot.core.quality_gate.judge import (
    JudgeDecision,
    JudgeOutput,
)

_KNOWN = frozenset({"rule.a", "rule.b"})


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("rule.a",),
    )


def _proposer_output() -> tuple[str, Mapping[str, Any]]:
    return ("remediate.tag-add", {"tag_name": "owner"})


def _retry_output() -> tuple[str, Mapping[str, Any]]:
    return ("remediate.tag-add", {"tag_name": "owner", "tag_value": "team-b"})


class _RecordingCritic:
    def __init__(self, outputs: list[CriticOutput]) -> None:
        self._queue = list(outputs)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def critique(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
    ) -> CriticOutput:
        self.calls.append(proposer_output)
        if not self._queue:
            raise AssertionError("critic queue exhausted")
        return self._queue.pop(0)


class _RaisingCritic:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def critique(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
    ) -> CriticOutput:
        raise self._exc


class _RecordingJudge:
    def __init__(self, outputs: list[JudgeOutput]) -> None:
        self._queue = list(outputs)
        self.calls: list[tuple[tuple[str, Mapping[str, Any]], CriticOutput]] = []

    async def judge(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
        critic_output: CriticOutput,
    ) -> JudgeOutput:
        self.calls.append((proposer_output, critic_output))
        if not self._queue:
            raise AssertionError("judge queue exhausted")
        return self._queue.pop(0)


class _RaisingJudge:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def judge(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
        critic_output: CriticOutput,
    ) -> JudgeOutput:
        raise self._exc


async def _retry_stub(candidate: QualityCandidate, directive: str) -> tuple[str, Mapping[str, Any]]:
    return _retry_output()


async def _retry_raiser(
    candidate: QualityCandidate, directive: str
) -> tuple[str, Mapping[str, Any]]:
    raise RuntimeError("proposer offline")


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestConfig:
    def test_rejects_negative_max_rounds(self) -> None:
        with pytest.raises(ValueError, match="max_rounds"):
            DebateOrchestratorConfig(max_rounds=-1)

    def test_rejects_max_rounds_above_one(self) -> None:
        with pytest.raises(ValueError, match="max_rounds"):
            DebateOrchestratorConfig(max_rounds=2)


class TestRetryArgumentValidation:
    @pytest.mark.asyncio
    async def test_retry_proposer_required_when_max_rounds_ge_1(self) -> None:
        orch = DebateOrchestrator(
            critic=_RecordingCritic([CriticOutput(stance=CriticStance.AGREE)]),
            judge=_RecordingJudge([JudgeOutput(decision=JudgeDecision.ACCEPT, justification="ok")]),
        )
        with pytest.raises(ValueError, match="retry_proposer MUST be supplied"):
            await orch.run(
                candidate=_candidate(),
                proposer_output=_proposer_output(),
                known_rule_ids=_KNOWN,
                retry_proposer=None,
            )


# ---------------------------------------------------------------------------
# Round 1 happy paths + Critic early-exit
# ---------------------------------------------------------------------------


class TestRoundOne:
    @pytest.mark.asyncio
    async def test_critic_agrees_judge_proceeds_single_round(self) -> None:
        critic = _RecordingCritic([CriticOutput(stance=CriticStance.AGREE)])
        judge = _RecordingJudge(
            [JudgeOutput(decision=JudgeDecision.ACCEPT, justification="matches rule")]
        )
        orch = DebateOrchestrator(critic=critic, judge=judge)
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert isinstance(outcome, DebateOutcome)
        assert outcome.verdict is DebateVerdict.PROCEED
        assert outcome.rounds == 1
        assert outcome.final_proposer_output == _proposer_output()
        assert len(critic.calls) == 1
        assert len(judge.calls) == 1

    @pytest.mark.asyncio
    async def test_critic_aborts_short_circuits_before_judge(self) -> None:
        """A high-severity Critic objection MUST prevent the Judge
        turn from firing at all - token cost matters."""

        critic = _RecordingCritic(
            [
                CriticOutput(
                    stance=CriticStance.CHALLENGE,
                    objections=(
                        CriticObjection(
                            severity=CriticSeverity.HIGH,
                            cited_rule_id="rule.a",
                            description="blast radius exceeds cap",
                        ),
                    ),
                )
            ]
        )
        judge = _RecordingJudge([])  # empty - must NOT be called
        orch = DebateOrchestrator(critic=critic, judge=judge)
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert "critic aborted" in outcome.reason
        assert outcome.rounds == 1
        assert judge.calls == []

    @pytest.mark.asyncio
    async def test_critic_abstain_short_circuits(self) -> None:
        critic = _RecordingCritic([CriticOutput(stance=CriticStance.ABSTAIN)])
        judge = _RecordingJudge([])
        orch = DebateOrchestrator(critic=critic, judge=judge)
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert "abstain" in outcome.reason
        assert judge.calls == []

    @pytest.mark.asyncio
    async def test_judge_escalate_hil_aborts_after_one_round(self) -> None:
        critic = _RecordingCritic([CriticOutput(stance=CriticStance.AGREE)])
        judge = _RecordingJudge(
            [
                JudgeOutput(
                    decision=JudgeDecision.ESCALATE_HIL,
                    justification="risk exceeds bounds",
                )
            ]
        )
        orch = DebateOrchestrator(critic=critic, judge=judge)
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert "judge escalated" in outcome.reason
        assert outcome.rounds == 1


# ---------------------------------------------------------------------------
# Round 2 (retry) paths
# ---------------------------------------------------------------------------


class TestRetryRound:
    @pytest.mark.asyncio
    async def test_judge_retry_triggers_second_round_and_accepts(self) -> None:
        critic = _RecordingCritic(
            [
                CriticOutput(
                    stance=CriticStance.CHALLENGE,
                    objections=(
                        CriticObjection(
                            severity=CriticSeverity.MEDIUM,
                            cited_rule_id="rule.a",
                            description="param drift",
                        ),
                    ),
                ),
                CriticOutput(stance=CriticStance.AGREE),
            ]
        )
        judge = _RecordingJudge(
            [
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="tag_value looks off",
                    retry_directive="switch tag_value to team-b",
                ),
                JudgeOutput(decision=JudgeDecision.ACCEPT, justification="better"),
            ]
        )
        orch = DebateOrchestrator(critic=critic, judge=judge)
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.PROCEED
        assert outcome.rounds == 2
        # Final output is the retried one, not the original.
        assert outcome.final_proposer_output == _retry_output()
        assert len(critic.calls) == 2
        assert len(judge.calls) == 2

    @pytest.mark.asyncio
    async def test_judge_retry_but_max_rounds_zero_aborts(self) -> None:
        critic = _RecordingCritic([CriticOutput(stance=CriticStance.AGREE)])
        judge = _RecordingJudge(
            [
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="please retry",
                    retry_directive="do something",
                )
            ]
        )
        orch = DebateOrchestrator(
            critic=critic,
            judge=judge,
            config=DebateOrchestratorConfig(max_rounds=0),
        )
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert "max_rounds=0" in outcome.reason
        assert outcome.rounds == 1

    @pytest.mark.asyncio
    async def test_critic_abort_on_retry_aborts(self) -> None:
        critic = _RecordingCritic(
            [
                CriticOutput(stance=CriticStance.AGREE),
                CriticOutput(
                    stance=CriticStance.CHALLENGE,
                    objections=(
                        CriticObjection(
                            severity=CriticSeverity.HIGH,
                            cited_rule_id="rule.a",
                            description="worse after retry",
                        ),
                    ),
                ),
            ]
        )
        judge = _RecordingJudge(
            [
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="retry please",
                    retry_directive="do it",
                ),
            ]
        )
        orch = DebateOrchestrator(critic=critic, judge=judge)
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert "critic abort on retry" in outcome.reason
        assert outcome.rounds == 2

    @pytest.mark.asyncio
    async def test_judge_second_retry_request_aborts_max_rounds_exhausted(self) -> None:
        """A Judge that asks for ANOTHER retry after round 2 is
        refused - max_rounds=1 permits exactly one retry."""

        critic = _RecordingCritic(
            [
                CriticOutput(stance=CriticStance.AGREE),
                CriticOutput(stance=CriticStance.AGREE),
            ]
        )
        judge = _RecordingJudge(
            [
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="please try again",
                    retry_directive="tweak",
                ),
                JudgeOutput(
                    decision=JudgeDecision.REVISE_AND_RETRY,
                    justification="still not right",
                    retry_directive="tweak more",
                ),
            ]
        )
        orch = DebateOrchestrator(critic=critic, judge=judge)
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert "max_rounds exhausted" in outcome.reason
        assert outcome.rounds == 2


# ---------------------------------------------------------------------------
# Fail-closed error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_critic_exception_returns_abort_with_error_class(self) -> None:
        orch = DebateOrchestrator(
            critic=_RaisingCritic(RuntimeError("timeout")),
            judge=_RecordingJudge([]),
        )
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert outcome.error_class == "RuntimeError"
        assert "critic model error" in outcome.reason

    @pytest.mark.asyncio
    async def test_judge_exception_returns_abort_with_critic_output_preserved(
        self,
    ) -> None:
        critic_output = CriticOutput(stance=CriticStance.AGREE)
        orch = DebateOrchestrator(
            critic=_RecordingCritic([critic_output]),
            judge=_RaisingJudge(RuntimeError("boom")),
        )
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_stub,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert outcome.error_class == "RuntimeError"
        # Critic transcript IS preserved so the audit log can show
        # how far the debate got.
        assert outcome.critic_output is critic_output

    @pytest.mark.asyncio
    async def test_proposer_retry_exception_returns_abort(self) -> None:
        orch = DebateOrchestrator(
            critic=_RecordingCritic(
                [
                    CriticOutput(
                        stance=CriticStance.CHALLENGE,
                        objections=(
                            CriticObjection(
                                severity=CriticSeverity.MEDIUM,
                                cited_rule_id="rule.a",
                                description="drift",
                            ),
                        ),
                    ),
                ]
            ),
            judge=_RecordingJudge(
                [
                    JudgeOutput(
                        decision=JudgeDecision.REVISE_AND_RETRY,
                        justification="retry",
                        retry_directive="fix it",
                    )
                ]
            ),
        )
        outcome = await orch.run(
            candidate=_candidate(),
            proposer_output=_proposer_output(),
            known_rule_ids=_KNOWN,
            retry_proposer=_retry_raiser,
        )
        assert outcome.verdict is DebateVerdict.ABORT
        assert "proposer retry error" in outcome.reason
        assert outcome.error_class == "RuntimeError"
        assert outcome.rounds == 1
