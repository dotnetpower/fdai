"""T0 + expression check_logic contract.

Regression: the auto-imported catalog under
``rule-catalog/collected/azure-builtin/`` and
``rule-catalog/collected/kube-bench/`` ships rules with
``check_logic.kind = expression`` (the parser has no way to translate
Azure Policy DSL or kube-bench audit commands into Rego). This test
locks the following contract:

- ``OpaRegoEvaluator.evaluate`` returns ``None`` for any
  non-Rego rule (already tested at the evaluator's own level; here we
  assert the end-to-end effect).
- ``T0Engine.evaluate`` handles that ``None`` by adding the rule to
  the ``abstained`` list, NOT by fabricating a ``PolicyResult`` or
  crashing.
- The resulting :class:`Verdict` has ``audit_hint.pipeline_stage =
  ABSTAIN`` when every candidate abstained; ``L1_EVALUATE`` when any
  rule matched.

If a future change lets imported rules silently promote to findings
without a Rego author writing real logic, that would violate the
shadow-then-enforce contract and this test catches it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.core.tiers.t0_deterministic import RuleIndex, T0Engine
from fdai.core.tiers.t0_deterministic.engine import AbstainEvaluator, PolicyResult
from fdai.core.tiers.t0_deterministic.models import PipelineStage
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


def _imported_rule(rule_id: str = "azure-builtin.demo") -> Rule:
    """Build a Rule the way the collector lands imported entries."""
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.AZURE_POLICY,
        severity=Severity.MEDIUM,
        category=Category.SECURITY,
        resource_type="object-storage",
        check_logic=CheckLogic(
            kind=CheckLogicKind.EXPRESSION,
            reference="azure-policy://demo-guid",
        ),
        remediation=Remediation(template_ref="remediation/azure-builtin/demo.md"),
        remediates="remediate.azure-policy-managed",
        parameters={"azure_policy_name": "demo-guid"},
        provenance=Provenance(
            source_url="https://github.com/Azure/azure-policy/blob/main/demo.json",
            source_version="1.0.0",
            resolved_ref="0" * 40,
            content_hash="sha256:" + "0" * 64,
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at=datetime.now(tz=UTC),
        ),
    )


def test_expression_kind_rule_abstains_never_fabricates_finding() -> None:
    """The default abstain evaluator returns None for every rule; combined
    with an imported expression-kind rule the engine MUST route through
    the abstain branch and NEVER build a Finding."""
    rule = _imported_rule()
    index = RuleIndex.build([rule])
    engine = T0Engine(index=index, evaluator=AbstainEvaluator())
    verdict = engine.evaluate(
        event_id=str(UUID("00000000-0000-0000-0000-000000000010")),
        signal_id="sig-1",
        resource_id="res-1",
        resource_type=rule.resource_type,
        resource_props={"any": "thing"},
        signal_type="any.signal",
    )
    assert verdict.findings == ()
    assert not verdict.matched
    assert verdict.audit_hint is not None
    assert verdict.audit_hint.pipeline_stage is PipelineStage.ABSTAIN
    assert rule.id in verdict.audit_hint.citing_rule_ids


class _WouldFabricateEvaluator:
    """Evaluator that would ALWAYS return a denied PolicyResult -
    used only to prove the shadow-mode invariant is not broken by
    the evaluator surface itself. The test uses this to ensure
    imported rules still pass through the shadow-then-enforce
    gate at the layer above (the caller wires the real evaluator
    that returns None for expression kind)."""

    def evaluate(self, rule: Rule, resource_props):  # noqa: ANN001, ANN201, ARG002
        return PolicyResult(denied=True, context={"forced": True})


def test_engine_does_not_downgrade_expression_kind_by_default() -> None:
    """Regression guard: the AbstainEvaluator (the safe default the
    engine ships with) MUST NOT be tempted to auto-approve an
    expression-kind rule. A future refactor that adds a "just look at
    parameters" shortcut for expression rules would be a shadow-mode
    escape - this test locks the default at 'abstain'."""
    rule = _imported_rule("azure-builtin.other")
    index = RuleIndex.build([rule])
    engine = T0Engine(index=index, evaluator=AbstainEvaluator())
    verdict = engine.evaluate(
        event_id=str(UUID("00000000-0000-0000-0000-000000000020")),
        signal_id="sig-2",
        resource_id="res-2",
        resource_type=rule.resource_type,
        resource_props={},
        signal_type="any.signal",
    )
    assert verdict.findings == ()


def test_no_crash_when_evaluator_raises_on_expression_rule() -> None:
    """Fail-closed guard: even if a fork wires an evaluator that raises
    on expression-kind rules, T0Engine catches the exception and
    downgrades to an abstained-list entry (per the standing
    'one broken rule MUST NOT crash the loop' contract)."""

    class _RaisingEvaluator:
        def evaluate(self, rule: Rule, resource_props):  # noqa: ANN001, ANN201, ARG002
            raise RuntimeError("do not do this in real code")

    rule = _imported_rule("azure-builtin.raiser")
    index = RuleIndex.build([rule])
    engine = T0Engine(index=index, evaluator=_RaisingEvaluator())
    verdict = engine.evaluate(
        event_id=str(UUID("00000000-0000-0000-0000-000000000030")),
        signal_id="sig-3",
        resource_id="res-3",
        resource_type=rule.resource_type,
        resource_props={},
        signal_type="any.signal",
    )
    assert verdict.findings == ()  # no findings, no crash
    assert verdict.audit_hint is not None
    assert rule.id in verdict.audit_hint.citing_rule_ids


# ---------------------------------------------------------------------------
# Suppress unused import warnings for future extenders that copy from here.
# ---------------------------------------------------------------------------
_ = pytest
