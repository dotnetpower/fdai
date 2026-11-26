"""Tests for deterministic severity with explicit ranges for unknown facts."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.security.code_findings.models import InstanceFacts
from fdai.core.security.code_findings.severity import assess_advisory, assess_facts
from fdai.rule_catalog.code_security import (
    AttackComplexity,
    AttackVector,
    Impact,
    PrivilegesRequired,
    SeverityBand,
    UserInteraction,
)

from ._support import catalog

_FULL = InstanceFacts(
    impact=Impact.CODE_EXECUTION,
    attack_vector=AttackVector.NETWORK,
    attack_complexity=AttackComplexity.LOW,
    privileges_required=PrivilegesRequired.NONE,
    user_interaction=UserInteraction.NONE,
)


def test_fully_verified_facts_give_one_band() -> None:
    rubric = catalog().severity_rubric
    assessed = assess_facts(_FULL, (Impact.CODE_EXECUTION,), rubric)
    assert assessed.label == "critical"
    assert assessed.floor == assessed.ceiling == SeverityBand.CRITICAL
    assert assessed.unknown_facts == ()
    assert assessed.deciding_facts == ()


def test_authenticated_sql_injection_is_high_not_critical() -> None:
    facts = InstanceFacts(
        impact=Impact.DATA_WRITE,
        attack_vector=AttackVector.NETWORK,
        attack_complexity=AttackComplexity.LOW,
        privileges_required=PrivilegesRequired.LOW,
        user_interaction=UserInteraction.NONE,
    )
    assert assess_facts(facts, (Impact.DATA_WRITE,), catalog().severity_rubric).label == "high"


def test_authenticated_code_execution_is_high_not_critical() -> None:
    # CVSS AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H is 8.8, high; rubric 1.1.0 agrees.
    facts = InstanceFacts(
        impact=Impact.CODE_EXECUTION,
        attack_vector=AttackVector.NETWORK,
        attack_complexity=AttackComplexity.LOW,
        privileges_required=PrivilegesRequired.LOW,
        user_interaction=UserInteraction.NONE,
    )
    assessed = assess_facts(facts, (Impact.CODE_EXECUTION,), catalog().severity_rubric)
    assert (assessed.label, assessed.floor_points) == ("high", 8.9)


def test_high_attack_complexity_lowers_an_unauthenticated_critical_to_high() -> None:
    # CVSS AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H is 8.1, high.
    facts = InstanceFacts(
        impact=Impact.CODE_EXECUTION,
        attack_vector=AttackVector.NETWORK,
        attack_complexity=AttackComplexity.HIGH,
        privileges_required=PrivilegesRequired.NONE,
        user_interaction=UserInteraction.NONE,
    )
    rubric = catalog().severity_rubric
    assert assess_facts(facts, (Impact.CODE_EXECUTION,), rubric).label == "high"
    low = replace(facts, attack_complexity=AttackComplexity.LOW)
    assert assess_facts(low, (Impact.CODE_EXECUTION,), rubric).label == "critical"


def test_unknown_facts_give_undetermined_with_range_and_deciding_facts() -> None:
    assessed = assess_facts(InstanceFacts(), (Impact.CODE_EXECUTION,), catalog().severity_rubric)
    assert assessed.label == "undetermined"
    # Every exploitability fact at its least severe value: 10 - 3.0 - 1.5 - 2.0 - 1.0 = 2.5.
    assert assessed.floor == SeverityBand.LOW
    assert assessed.ceiling == SeverityBand.CRITICAL
    assert set(assessed.unknown_facts) == {
        "impact",
        "attack_vector",
        "attack_complexity",
        "privileges_required",
        "user_interaction",
    }
    # A single-value class impact range cannot move a bound, so impact is not deciding.
    assert "impact" not in assessed.deciding_facts
    assert "attack_vector" in assessed.deciding_facts
    assert "unknown" in assessed.rationale


def test_same_facts_and_rubric_are_reproducible() -> None:
    rubric = catalog().severity_rubric
    facts = InstanceFacts(impact=Impact.DATA_READ, attack_vector=AttackVector.LOCAL)
    first = assess_facts(facts, (Impact.DATA_READ,), rubric)
    assert all(assess_facts(facts, (Impact.DATA_READ,), rubric) == first for _ in range(20))


def test_non_deciding_unknown_fact_is_not_listed() -> None:
    facts = InstanceFacts(
        impact=Impact.LIMITED,
        attack_vector=AttackVector.NETWORK,
        attack_complexity=AttackComplexity.LOW,
        privileges_required=PrivilegesRequired.NONE,
    )
    assessed = assess_facts(facts, (Impact.LIMITED,), catalog().severity_rubric)
    assert assessed.label == "low"
    assert assessed.unknown_facts == ("user_interaction",)
    assert assessed.deciding_facts == ()


def test_advisory_scores_that_disagree_stay_visible() -> None:
    rubric = catalog().severity_rubric
    agreed = assess_advisory([("Trivy", 9.8), ("OSV-Scanner", 9.1)], rubric)
    assert agreed.label == "critical"
    split = assess_advisory([("Trivy", 9.8), ("GHAS", 7.5)], rubric)
    assert split.label == "undetermined"
    assert (split.floor, split.ceiling) == (SeverityBand.HIGH, SeverityBand.CRITICAL)
    assert split.deciding_facts == ("advisory_score_disagreement",)
