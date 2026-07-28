"""T0Engine - verdict emission, shadow invariance, fail-closed behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from fdai.core.tiers.t0_deterministic import (
    AbstainEvaluator,
    PipelineStage,
    PolicyResult,
    RuleIndex,
    T0Engine,
    Verdict,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Mode,
    Provenance,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)


def _rule(
    *,
    rule_id: str,
    resource_type: str,
    severity: Severity = Severity.HIGH,
    remediates: str = "remediate.tag-add",
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=severity,
        category=Category.SECURITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates=remediates,
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


class _AlwaysDeny:
    def __init__(self, *, context: dict[str, Any] | None = None) -> None:
        self._ctx = context or {"why": "test-deny"}

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del rule, resource_props
        return PolicyResult(denied=True, context=self._ctx)


class _AlwaysAllow:
    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del rule, resource_props
        return PolicyResult(denied=False, context={})


class _Boom:
    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del rule, resource_props
        raise RuntimeError("evaluator crashed")


class _AbstainOne:
    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        del resource_props
        return None if rule.id == "a.x" else PolicyResult(denied=False, context={})


def _engine(rules: list[Rule], evaluator: Any = None) -> T0Engine:
    return T0Engine(index=RuleIndex.build(rules), evaluator=evaluator)


def test_abstain_when_no_rule_matches_resource_type() -> None:
    engine = _engine([_rule(rule_id="a.x", resource_type="compute.vm")])
    verdict = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="object-storage",  # no rule for this type
        resource_props={},
    )
    assert isinstance(verdict, Verdict)
    assert verdict.findings == ()
    assert verdict.audit_hint is not None
    assert verdict.audit_hint.pipeline_stage is PipelineStage.ABSTAIN
    assert verdict.audit_hint.tier == "t0"
    assert verdict.audit_hint.mode is Mode.SHADOW
    assert verdict.audit_hint.citing_rule_ids == ()
    assert verdict.audit_hint.reason == "no_rule_matched_resource_type"


def test_default_evaluator_abstains_and_records_candidate_ids() -> None:
    rules = [
        _rule(rule_id="a.x", resource_type="compute.vm"),
        _rule(rule_id="b.x", resource_type="compute.vm", severity=Severity.LOW),
    ]
    engine = _engine(rules)  # default: AbstainEvaluator
    verdict = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )
    assert verdict.findings == ()
    hint = verdict.audit_hint
    assert hint is not None
    assert hint.pipeline_stage is PipelineStage.ABSTAIN
    assert hint.citing_rule_ids == ("a.x", "b.x")
    assert hint.reason == "evaluator_abstained_on_all_candidates"


def test_deny_evaluator_emits_findings_in_severity_order() -> None:
    rules = [
        _rule(rule_id="a.low", resource_type="compute.vm", severity=Severity.LOW),
        _rule(rule_id="b.high", resource_type="compute.vm", severity=Severity.HIGH),
        _rule(rule_id="c.critical", resource_type="compute.vm", severity=Severity.CRITICAL),
    ]
    engine = _engine(rules, evaluator=_AlwaysDeny(context={"prop": "public_access"}))
    verdict = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={"public_access": True},
    )
    assert [f.rule_id for f in verdict.findings] == ["c.critical", "b.high", "a.low"]
    hint = verdict.audit_hint
    assert hint is not None
    assert hint.pipeline_stage is PipelineStage.L1_EVALUATE
    assert hint.mode is Mode.SHADOW
    assert hint.reason is None
    # Every candidate is cited, regardless of match order.
    assert set(hint.citing_rule_ids) == {"c.critical", "b.high", "a.low"}


def test_allow_evaluator_emits_abstain_with_no_rule_denied_reason() -> None:
    rules = [_rule(rule_id="a.x", resource_type="compute.vm")]
    engine = _engine(rules, evaluator=_AlwaysAllow())
    verdict = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )
    assert verdict.findings == ()
    hint = verdict.audit_hint
    assert hint is not None
    assert hint.pipeline_stage is PipelineStage.ABSTAIN
    assert hint.reason == "no_rule_denied"


def test_evaluator_exception_is_fail_closed() -> None:
    """One broken evaluator MUST NOT crash the engine or hide other rules."""
    rules = [
        _rule(rule_id="a.x", resource_type="compute.vm"),
        _rule(rule_id="b.x", resource_type="compute.vm"),
    ]
    engine = _engine(rules, evaluator=_Boom())
    verdict = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )
    assert verdict.findings == ()
    hint = verdict.audit_hint
    assert hint is not None
    assert hint.pipeline_stage is PipelineStage.ABSTAIN
    assert hint.reason == "evaluator_abstained_on_all_candidates"
    # Both rules still cited so an operator can see what SHOULD have run.
    assert set(hint.citing_rule_ids) == {"a.x", "b.x"}


def test_partial_evaluator_abstain_is_attributed_accurately() -> None:
    rules = [
        _rule(rule_id="a.x", resource_type="compute.vm"),
        _rule(rule_id="b.x", resource_type="compute.vm"),
    ]
    verdict = _engine(rules, evaluator=_AbstainOne()).evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )

    assert verdict.findings == ()
    assert verdict.audit_hint is not None
    assert verdict.audit_hint.reason == "evaluator_abstained_on_some_candidates"


def test_shadow_mode_invariant_holds_on_every_verdict() -> None:
    """Property test: shadow-mode is emitted regardless of the evaluator outcome."""
    rules = [_rule(rule_id="a.x", resource_type="compute.vm")]
    for evaluator in (None, _AlwaysAllow(), _AlwaysDeny(), _Boom()):
        engine = _engine(rules, evaluator=evaluator)
        verdict = engine.evaluate(
            event_id="evt-1",
            signal_id="sig-1",
            resource_id="rid-1",
            resource_type="compute.vm",
            resource_props={},
        )
        assert verdict.audit_hint is not None
        assert verdict.audit_hint.mode is Mode.SHADOW


def test_finding_id_is_stable_across_replays() -> None:
    rule = _rule(rule_id="a.x", resource_type="compute.vm")
    engine = _engine([rule], evaluator=_AlwaysDeny())
    v1 = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )
    v2 = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )
    assert v1.findings[0].finding_id == v2.findings[0].finding_id


def test_abstain_evaluator_returns_none() -> None:
    """Directly exercise the default P1 W-2 evaluator so its abstain
    contract is asserted, not just implied by engine behavior."""
    rule = _rule(rule_id="a.x", resource_type="compute.vm")
    assert AbstainEvaluator().evaluate(rule, {"whatever": True}) is None


def test_verdict_matched_property() -> None:
    rule = _rule(rule_id="a.x", resource_type="compute.vm")
    engine = _engine([rule], evaluator=_AlwaysDeny())
    v = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )
    assert v.matched is True
    engine2 = _engine([rule], evaluator=_AlwaysAllow())
    v2 = engine2.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
    )
    assert v2.matched is False


@pytest.mark.parametrize(
    "signal_type",
    [None, "config.public_access.enabled", "property.public_access.changed"],
)
def test_signal_type_is_currently_informational(signal_type: str | None) -> None:
    rule = _rule(rule_id="a.x", resource_type="compute.vm")
    engine = _engine([rule], evaluator=_AlwaysDeny())
    v = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="compute.vm",
        resource_props={},
        signal_type=signal_type,
    )
    assert [f.rule_id for f in v.findings] == ["a.x"]
