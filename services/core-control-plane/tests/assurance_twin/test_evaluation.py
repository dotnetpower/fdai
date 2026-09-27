from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.assurance_twin import (
    AssuranceTwinEvaluationUnavailableError,
    build_baseline_projection,
    evaluate_complete_posture,
)
from fdai.core.tiers.t0_deterministic import (
    PolicyResult,
    RuleIndex,
    T0Engine,
)
from fdai.core.tiers.t0_deterministic.models import RegoEvaluationReceipt
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Remediation,
    Rule,
    RuleSource,
    Severity,
    SubmissionCriterion,
    SubmissionCriterionKind,
)
from fdai.shared.providers.projection import ResourceRef

_REVISION = "sha256:" + "a" * 64
_GENERATION_TIME = datetime(2026, 9, 27, tzinfo=UTC)


def _rule(
    rule_id: str,
    resource_type: str = "compute.vm",
    *,
    required_property: str | None = None,
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
        evaluates=[required_property] if required_property is not None else ["*"],
        submission_criteria=(
            [
                SubmissionCriterion(
                    kind=SubmissionCriterionKind.PROPERTY_EXISTS,
                    value=required_property,
                )
            ]
            if required_property is not None
            else []
        ),
    )


class _ReceiptEvaluator:
    generation_digest = "sha256:" + "2" * 64

    def __init__(self, *, abstain_rule: str | None = None, receipts: bool = True) -> None:
        self._abstain_rule = abstain_rule
        self._receipts = receipts

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        if rule.id == self._abstain_rule:
            return None
        denied = resource_props.get("deny") is True
        receipt = (
            RegoEvaluationReceipt(
                decision_path=f"fdai.{rule.id}.deny",
                opa_version="1.0.0",
                parser_id="opa-ast",
                parser_version="1.0.0",
                policy_source_digest="sha256:" + "b" * 64,
                normalized_semantic_digest="sha256:" + "c" * 64,
                input_evidence_digest="sha256:" + ("d" if denied else "e") * 64,
                denied=denied,
                result_digest="sha256:" + ("f" if denied else "1") * 64,
            )
            if self._receipts
            else None
        )
        return PolicyResult(
            denied=denied,
            context={"deny_reason": "public access"} if denied else {},
            evaluation_receipt=receipt,
        )


def _projection() -> Any:
    return build_baseline_projection(
        (
            (ResourceRef("compute.vm", "vm-a"), {"deny": True}),
            (ResourceRef("compute.vm", "vm-b"), {"deny": False}),
        )
    )


def test_complete_posture_uses_exact_t0_receipts() -> None:
    rules = (_rule("rule.example"),)
    result = evaluate_complete_posture(
        engine=T0Engine(index=RuleIndex.build(rules), evaluator=_ReceiptEvaluator()),
        rules=rules,
        projection=_projection(),
        inventory_revision=_REVISION,
        rule_generation_time=_GENERATION_TIME,
    )

    assert result.evaluated_rule_ids == ("rule.example",)
    assert len(result.coverage_refs) == 3
    assert result.coverage_refs[0] == _REVISION
    assert result.coverage_refs[1] == result.rule_set_digest
    assert len(result.findings) == 1
    assert result.findings[0].resource.ref == "vm-a"
    assert result.findings[0].reason == "public access"


@pytest.mark.parametrize(
    "evaluator",
    [
        _ReceiptEvaluator(abstain_rule="rule.example"),
        _ReceiptEvaluator(receipts=False),
    ],
)
def test_incomplete_rule_evaluation_is_unavailable(evaluator: _ReceiptEvaluator) -> None:
    rules = (_rule("rule.example"),)
    with pytest.raises(AssuranceTwinEvaluationUnavailableError):
        evaluate_complete_posture(
            engine=T0Engine(index=RuleIndex.build(rules), evaluator=evaluator),
            rules=rules,
            projection=_projection(),
            inventory_revision=_REVISION,
            rule_generation_time=_GENERATION_TIME,
        )


def test_no_applicable_rules_cannot_synthesize_clear() -> None:
    rules = (_rule("rule.example", resource_type="object-storage"),)
    with pytest.raises(AssuranceTwinEvaluationUnavailableError, match="no applicable"):
        evaluate_complete_posture(
            engine=T0Engine(index=RuleIndex.build(rules), evaluator=_ReceiptEvaluator()),
            rules=rules,
            projection=_projection(),
            inventory_revision=_REVISION,
            rule_generation_time=_GENERATION_TIME,
        )


def test_one_uncovered_resource_makes_the_whole_projection_unavailable() -> None:
    rules = (_rule("rule.example"),)
    projection = build_baseline_projection(
        (
            (ResourceRef("compute.vm", "vm-a"), {"deny": False}),
            (ResourceRef("object-storage", "storage-a"), {"deny": False}),
        )
    )
    with pytest.raises(AssuranceTwinEvaluationUnavailableError, match="no applicable"):
        evaluate_complete_posture(
            engine=T0Engine(index=RuleIndex.build(rules), evaluator=_ReceiptEvaluator()),
            rules=rules,
            projection=projection,
            inventory_revision=_REVISION,
            rule_generation_time=_GENERATION_TIME,
        )


def test_missing_declared_rule_input_cannot_synthesize_clear() -> None:
    rules = (
        _rule(
            "rule.example",
            required_property="property.compute.vm.private_endpoints",
        ),
    )
    projection = build_baseline_projection(
        ((ResourceRef("compute.vm", "vm-a"), {"public_network_access": False}),)
    )
    with pytest.raises(AssuranceTwinEvaluationUnavailableError, match="input property"):
        evaluate_complete_posture(
            engine=T0Engine(index=RuleIndex.build(rules), evaluator=_ReceiptEvaluator()),
            rules=rules,
            projection=projection,
            inventory_revision=_REVISION,
            rule_generation_time=_GENERATION_TIME,
        )


def test_findings_above_operator_bound_are_unavailable() -> None:
    rules = (_rule("rule.example"),)
    projection = build_baseline_projection(
        (ResourceRef("compute.vm", f"vm-{index:03d}"), {"deny": True}) for index in range(201)
    )
    with pytest.raises(AssuranceTwinEvaluationUnavailableError, match="projection bound"):
        evaluate_complete_posture(
            engine=T0Engine(index=RuleIndex.build(rules), evaluator=_ReceiptEvaluator()),
            rules=rules,
            projection=projection,
            inventory_revision=_REVISION,
            rule_generation_time=_GENERATION_TIME,
        )
