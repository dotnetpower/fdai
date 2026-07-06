"""Unit tests for :mod:`aiopspilot.core.quality_gate.judge`."""

from __future__ import annotations

import pytest

from aiopspilot.core.quality_gate.judge import (
    JudgeDecision,
    JudgeOutput,
    JudgeVerdict,
    evaluate_judge_output,
)

_KNOWN = frozenset({"rule.a", "rule.b", "rule.c"})


class TestJudgeOutput:
    def test_rejects_blank_justification(self) -> None:
        with pytest.raises(ValueError, match="justification"):
            JudgeOutput(decision=JudgeDecision.ACCEPT, justification="   ")


class TestAcceptDecision:
    def test_accept_with_no_citations_proceeds(self) -> None:
        output = JudgeOutput(decision=JudgeDecision.ACCEPT, justification="looks good")
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.PROCEED

    def test_accept_with_only_known_citations_proceeds(self) -> None:
        output = JudgeOutput(
            decision=JudgeDecision.ACCEPT,
            justification="looks good",
            citations=("rule.a", "rule.c"),
        )
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.PROCEED

    def test_accept_with_unknown_citation_escalates(self) -> None:
        """An ungrounded citation MUST NOT be honored - the transcript
        would carry a phantom rule reference."""

        output = JudgeOutput(
            decision=JudgeDecision.ACCEPT,
            justification="looks good",
            citations=("rule.a", "phantom.rule"),
        )
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.ESCALATE


class TestReviseAndRetryDecision:
    def test_retry_with_directive_and_known_citations_retries(self) -> None:
        output = JudgeOutput(
            decision=JudgeDecision.REVISE_AND_RETRY,
            justification="params look off",
            retry_directive="switch tag_value to team-b",
            citations=("rule.b",),
        )
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.RETRY

    def test_retry_without_directive_escalates(self) -> None:
        """A retry request without a directive is a defect - the
        Proposer would not know what to change."""

        output = JudgeOutput(
            decision=JudgeDecision.REVISE_AND_RETRY,
            justification="something is wrong",
            retry_directive=None,
        )
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.ESCALATE

    def test_retry_with_blank_directive_escalates(self) -> None:
        output = JudgeOutput(
            decision=JudgeDecision.REVISE_AND_RETRY,
            justification="something is wrong",
            retry_directive="   ",
        )
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.ESCALATE

    def test_retry_with_unknown_citation_escalates(self) -> None:
        output = JudgeOutput(
            decision=JudgeDecision.REVISE_AND_RETRY,
            justification="params look off",
            retry_directive="switch tag_value",
            citations=("rule.phantom",),
        )
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.ESCALATE


class TestEscalateHilDecision:
    def test_escalate_hil_returns_escalate(self) -> None:
        output = JudgeOutput(
            decision=JudgeDecision.ESCALATE_HIL,
            justification="risk exceeds our confidence bounds",
        )
        assert evaluate_judge_output(output, known_rule_ids=_KNOWN) is JudgeVerdict.ESCALATE


class TestCatalogSeed:
    def test_shipped_judge_prompt_loads_and_is_shadow_mode(self) -> None:
        from pathlib import Path

        import yaml

        from aiopspilot.core.prompts.registry import FileSystemPromptRegistry

        repo_root = Path(__file__).resolve().parents[2]
        raw = yaml.safe_load(
            (repo_root / "rule-catalog" / "prompts" / "base" / "t2-judge.v1.yaml").read_text()
        )
        assert raw["id"] == "t2-judge"
        assert raw["version"] == 1
        assert raw["layer"] == "judge"
        assert raw["default_mode"] == "shadow"
        assert raw["applies_to"] == ["t1.judge"]
        registry = FileSystemPromptRegistry(repo_root / "rule-catalog")
        artifacts = registry.artifacts()
        ids = {a.id for a in artifacts}
        assert "t2-judge" in ids
