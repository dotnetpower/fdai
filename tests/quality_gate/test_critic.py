"""Unit tests for :mod:`aiopspilot.core.quality_gate.critic`."""

from __future__ import annotations

import pytest

from aiopspilot.core.quality_gate.critic import (
    CriticObjection,
    CriticOutput,
    CriticSeverity,
    CriticStance,
    CriticVerdict,
    evaluate_critic_output,
)

_KNOWN = frozenset({"rule.a", "rule.b", "rule.c"})


class TestCriticObjection:
    def test_rejects_blank_cited_rule_id(self) -> None:
        with pytest.raises(ValueError, match="cited_rule_id"):
            CriticObjection(
                severity=CriticSeverity.LOW,
                cited_rule_id="   ",
                description="something",
            )

    def test_rejects_blank_description(self) -> None:
        with pytest.raises(ValueError, match="description"):
            CriticObjection(
                severity=CriticSeverity.LOW,
                cited_rule_id="rule.a",
                description="",
            )


class TestAgreeStance:
    def test_agree_with_no_objections_endorses(self) -> None:
        output = CriticOutput(stance=CriticStance.AGREE)
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.ENDORSE

    def test_agree_with_low_severity_objection_still_endorses(self) -> None:
        """A low-severity nit alongside AGREE is not a contradiction -
        the Critic agreed and left a note; the orchestrator proceeds."""

        output = CriticOutput(
            stance=CriticStance.AGREE,
            objections=(
                CriticObjection(
                    severity=CriticSeverity.LOW,
                    cited_rule_id="rule.a",
                    description="minor nit",
                ),
            ),
        )
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.ENDORSE

    def test_agree_with_high_severity_objection_aborts_as_self_contradiction(self) -> None:
        """A Critic that says AGREE but flags a HIGH-severity issue is
        self-contradictory and MUST route to HIL; we do not honor the
        surface-level agreement."""

        output = CriticOutput(
            stance=CriticStance.AGREE,
            objections=(
                CriticObjection(
                    severity=CriticSeverity.HIGH,
                    cited_rule_id="rule.a",
                    description="critical blast radius overrun",
                ),
            ),
        )
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.ABORT


class TestAbstainStance:
    def test_abstain_short_circuits_ignoring_objections(self) -> None:
        """ABSTAIN is a hard signal - the evaluator does not second-
        guess by looking at any accompanying objections."""

        output = CriticOutput(
            stance=CriticStance.ABSTAIN,
            objections=(
                CriticObjection(
                    severity=CriticSeverity.HIGH,
                    cited_rule_id="unknown-rule",  # would be ABSTAIN anyway
                    description="unclear",
                ),
            ),
        )
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.ABSTAIN


class TestChallengeStance:
    def test_challenge_with_medium_objections_retries(self) -> None:
        output = CriticOutput(
            stance=CriticStance.CHALLENGE,
            objections=(
                CriticObjection(
                    severity=CriticSeverity.MEDIUM,
                    cited_rule_id="rule.b",
                    description="parameter drift",
                    alt_action_type="remediate.tag-add",
                ),
            ),
        )
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.RETRY

    def test_challenge_with_high_severity_aborts(self) -> None:
        output = CriticOutput(
            stance=CriticStance.CHALLENGE,
            objections=(
                CriticObjection(
                    severity=CriticSeverity.MEDIUM,
                    cited_rule_id="rule.a",
                    description="minor",
                ),
                CriticObjection(
                    severity=CriticSeverity.HIGH,
                    cited_rule_id="rule.c",
                    description="blast radius exceeds cap",
                ),
            ),
        )
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.ABORT

    def test_challenge_with_empty_objections_abstains(self) -> None:
        """A challenge with no evidence is a defect, not a signal."""

        output = CriticOutput(stance=CriticStance.CHALLENGE)
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.ABSTAIN

    def test_challenge_with_unknown_citation_abstains(self) -> None:
        """An ungrounded challenge cannot land in the audit trail
        without breaking the grounding invariant; we route to HIL
        instead of guessing."""

        output = CriticOutput(
            stance=CriticStance.CHALLENGE,
            objections=(
                CriticObjection(
                    severity=CriticSeverity.MEDIUM,
                    cited_rule_id="rule.not-in-catalog",
                    description="phantom citation",
                ),
            ),
        )
        assert evaluate_critic_output(output, known_rule_ids=_KNOWN) is CriticVerdict.ABSTAIN


class TestCatalogSeed:
    """The shipped catalog seed for the Critic role loads as a
    ``layer: base`` prompt applying to ``t2.critic`` and defaults to
    shadow mode per the Wave 4 alpha rollout gate."""

    def test_shipped_critic_prompt_loads_and_is_shadow_mode(self) -> None:
        from pathlib import Path

        import yaml

        from aiopspilot.core.prompts.registry import FileSystemPromptRegistry

        repo_root = Path(__file__).resolve().parents[2]
        raw = yaml.safe_load(
            (repo_root / "rule-catalog" / "prompts" / "base" / "t2-critic.v1.yaml").read_text()
        )
        assert raw["id"] == "t2-critic"
        assert raw["version"] == 1
        assert raw["layer"] == "critic"
        assert raw["default_mode"] == "shadow"
        assert raw["applies_to"] == ["t2.critic"]
        # The whole catalog still loads cleanly with the new artifact in place.
        registry = FileSystemPromptRegistry(repo_root / "rule-catalog")
        artifacts = registry.artifacts()
        ids = {a.id for a in artifacts}
        assert "t2-critic" in ids
