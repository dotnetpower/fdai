"""RuleBasedVerifier - the first non-fake VerifierPolicy.

Covers the four semantic outcomes the verifier must express:

- ``True``  - cited rule authorizes the action_type on the target type.
- ``False`` - cited rules exist, none authorize the action_type.
- ``None``  - no resolvable cited rules (verifier abstains; grounding
  leg surfaces the reason).
- ``True``  via ``alternatives[]`` - a cited rule ranks the candidate
  action_type as an authorized alternate.
- Target-type filter - a cited rule whose ``resource_type`` differs
  from the target is skipped rather than counted as authorization.
"""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.quality_gate import (
    QualityCandidate,
    RuleBasedVerifier,
)
from fdai.shared.contracts.models import Rule


def _make_rule(
    valid_rule: dict[str, Any],
    *,
    rule_id: str,
    resource_type: str = "compute.vm",
    remediates: str = "remediate.tag-add",
    alternatives: tuple[str, ...] = (),
) -> Rule:
    payload = dict(valid_rule)
    payload["id"] = rule_id
    payload["resource_type"] = resource_type
    payload["remediates"] = remediates
    if alternatives:
        payload["alternatives"] = list(alternatives)
    return Rule.model_validate(payload)


def _candidate(
    *,
    action_type: str = "remediate.tag-add",
    target_resource_ref: str = "vm-1",
    target_resource_type: str | None = "compute.vm",
    cited_rule_ids: tuple[str, ...] = (),
) -> QualityCandidate:
    return QualityCandidate(
        action_type=action_type,
        target_resource_ref=target_resource_ref,
        target_resource_type=target_resource_type,
        params={"owner": "team-a"},
        cited_rule_ids=cited_rule_ids,
    )


def test_verifier_abstains_without_cited_rules(valid_rule: dict[str, Any]) -> None:
    rule = _make_rule(valid_rule, rule_id="rule.a")
    verifier = RuleBasedVerifier(rules_by_id={"rule.a": rule})
    assert verifier.verify(_candidate(cited_rule_ids=())) is None


def test_verifier_abstains_when_all_citations_unknown(valid_rule: dict[str, Any]) -> None:
    """Unknown ids drop out at lookup; if nothing resolves, abstain."""
    rule = _make_rule(valid_rule, rule_id="rule.a")
    verifier = RuleBasedVerifier(rules_by_id={"rule.a": rule})
    assert verifier.verify(_candidate(cited_rule_ids=("rule.does-not-exist",))) is None


def test_verifier_returns_true_when_cited_rule_authorizes_action(
    valid_rule: dict[str, Any],
) -> None:
    rule = _make_rule(
        valid_rule,
        rule_id="rule.a",
        resource_type="compute.vm",
        remediates="remediate.tag-add",
    )
    verifier = RuleBasedVerifier(
        rules_by_id={"rule.a": rule},
        target_resource_type_lookup={"vm-1": "compute.vm"},
    )
    assert (
        verifier.verify(
            _candidate(
                action_type="remediate.tag-add",
                target_resource_ref="vm-1",
                cited_rule_ids=("rule.a",),
            )
        )
        is True
    )


def test_verifier_returns_false_when_no_cited_rule_authorizes_action(
    valid_rule: dict[str, Any],
) -> None:
    """Cited rule exists but its remediates != candidate.action_type."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.a",
        remediates="remediate.tag-add",
    )
    verifier = RuleBasedVerifier(rules_by_id={"rule.a": rule})
    assert (
        verifier.verify(
            _candidate(
                action_type="remediate.invented-action",
                cited_rule_ids=("rule.a",),
            )
        )
        is False
    )


def test_verifier_accepts_alternatives_authorization(valid_rule: dict[str, Any]) -> None:
    rule = _make_rule(
        valid_rule,
        rule_id="rule.a",
        remediates="remediate.tag-add",
        alternatives=("remediate.right-size",),
    )
    verifier = RuleBasedVerifier(rules_by_id={"rule.a": rule})
    assert (
        verifier.verify(
            _candidate(
                action_type="remediate.right-size",
                cited_rule_ids=("rule.a",),
            )
        )
        is True
    )


def test_verifier_skips_rule_of_wrong_target_type(valid_rule: dict[str, Any]) -> None:
    """Rule authored for object-storage does NOT authorize an action on a VM."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.storage",
        resource_type="object-storage",
        remediates="remediate.tag-add",
    )
    verifier = RuleBasedVerifier(
        rules_by_id={"rule.storage": rule},
        target_resource_type_lookup={"vm-1": "compute.vm"},
    )
    # Cited rule loaded, but wrong resource_type → deny (explicit False).
    assert (
        verifier.verify(
            _candidate(
                action_type="remediate.tag-add",
                target_resource_ref="vm-1",
                cited_rule_ids=("rule.storage",),
            )
        )
        is False
    )


def test_verifier_abstains_when_target_type_is_unresolved(valid_rule: dict[str, Any]) -> None:
    """No candidate type or lookup means the verifier cannot authorize."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.a",
        resource_type="object-storage",
        remediates="remediate.tag-add",
    )
    verifier = RuleBasedVerifier(rules_by_id={"rule.a": rule})
    assert (
        verifier.verify(
            _candidate(
                action_type="remediate.tag-add",
                target_resource_type=None,
                cited_rule_ids=("rule.a",),
            )
        )
        is None
    )


def test_verifier_abstains_when_lookup_missing_target(
    valid_rule: dict[str, Any],
) -> None:
    """A lookup miss cannot authorize an action on an unknown target type."""
    rule = _make_rule(
        valid_rule,
        rule_id="rule.a",
        resource_type="object-storage",
        remediates="remediate.tag-add",
    )
    verifier = RuleBasedVerifier(
        rules_by_id={"rule.a": rule},
        target_resource_type_lookup={"vm-1": "compute.vm"},
    )
    assert (
        verifier.verify(
            _candidate(
                action_type="remediate.tag-add",
                target_resource_ref="unknown-ref",
                target_resource_type=None,
                cited_rule_ids=("rule.a",),
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_rulebased_verifier_composes_with_quality_gate(
    valid_rule: dict[str, Any],
) -> None:
    """End-to-end: gate.evaluate() sees the verifier's True path."""
    from fdai.core.quality_gate import QualityGate, QualityGateConfig, QualityOutcome
    from fdai.core.quality_gate.testing import (
        InMemoryGroundingSource,
        MatchTypeCrossCheckModel,
    )

    rule = _make_rule(
        valid_rule,
        rule_id="rule.a",
        remediates="remediate.tag-add",
    )
    gate = QualityGate(
        verifier=RuleBasedVerifier(rules_by_id={"rule.a": rule}),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MatchTypeCrossCheckModel(model_id="fake-2"),
        ),
        grounding=InMemoryGroundingSource({"rule.a": rule}),
        config=QualityGateConfig(confidence_threshold=0.0),
    )
    candidate = QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="vm-1",
        target_resource_type="compute.vm",
        params={"owner": "team-a"},
        cited_rule_ids=("rule.a",),
        confidence_signals={"verifier_margin": 0.9, "retrieval": 0.9},
    )
    decision = await gate.evaluate(candidate)
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.reasons == ()


@pytest.mark.asyncio
async def test_rulebased_verifier_denies_invented_action(valid_rule: dict[str, Any]) -> None:
    from fdai.core.quality_gate import QualityGate, QualityGateConfig, QualityOutcome
    from fdai.core.quality_gate.testing import (
        InMemoryGroundingSource,
        MatchTypeCrossCheckModel,
    )

    rule = _make_rule(
        valid_rule,
        rule_id="rule.a",
        remediates="remediate.tag-add",
    )
    gate = QualityGate(
        verifier=RuleBasedVerifier(rules_by_id={"rule.a": rule}),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MatchTypeCrossCheckModel(model_id="fake-2"),
        ),
        grounding=InMemoryGroundingSource({"rule.a": rule}),
        config=QualityGateConfig(confidence_threshold=0.0),
    )
    invented = QualityCandidate(
        action_type="remediate.invented",
        target_resource_ref="vm-1",
        target_resource_type="compute.vm",
        params={},
        cited_rule_ids=("rule.a",),
    )
    decision = await gate.evaluate(invented)
    # Verifier explicit deny short-circuits the gate.
    assert decision.outcome is QualityOutcome.DENY
    assert decision.reasons == ("verifier_rejected",)
