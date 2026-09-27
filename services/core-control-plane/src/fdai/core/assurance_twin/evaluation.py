"""Complete deterministic Rule evaluation for one retained Twin projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime

from fdai.core.assurance_twin.projection import InMemoryProjection
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.models.rule import SubmissionCriterionKind
from fdai.shared.providers.projection import Finding, ResourceRef

_SIGNAL_TYPE = "inventory.resource_observed"
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_MAX_FINDINGS = 200


class AssuranceTwinEvaluationUnavailableError(ValueError):
    """The deterministic pass cannot prove complete Rule coverage."""


@dataclass(frozen=True, slots=True)
class CompletePostureEvaluation:
    """Content-addressed result of one complete deterministic posture pass."""

    findings: tuple[Finding, ...]
    evaluated_rule_ids: tuple[str, ...]
    rule_set_digest: str
    rule_generation_digest: str
    rule_generation_time: datetime
    coverage_refs: tuple[str, ...]


def evaluate_complete_posture(
    *,
    engine: T0Engine,
    rules: tuple[Rule, ...],
    projection: InMemoryProjection,
    inventory_revision: str,
    rule_generation_time: datetime,
) -> CompletePostureEvaluation:
    """Evaluate every applicable Rule and reject partial or receipt-free results."""

    if not _valid_digest(inventory_revision):
        raise ValueError("Assurance Twin Inventory revision MUST be a canonical digest")
    if rule_generation_time.tzinfo is None or rule_generation_time.utcoffset() is None:
        raise ValueError("Assurance Twin Rule generation time MUST be timezone-aware")
    rules_by_id = {rule.id: rule for rule in rules}
    if not rules_by_id or len(rules_by_id) != len(rules):
        raise AssuranceTwinEvaluationUnavailableError(
            "Assurance Twin Rule generation is empty or ambiguous"
        )

    evaluated: set[str] = set()
    findings: list[Finding] = []
    coverage: list[dict[str, object]] = []
    for resource in sorted(
        projection.resources,
        key=lambda item: (item.resource_type, item.ref),
    ):
        resource_properties = projection.properties(resource)
        verdict = engine.evaluate(
            event_id=f"assurance-twin:{inventory_revision}:{resource.ref}",
            signal_id=inventory_revision,
            resource_id=resource.ref,
            resource_type=resource.resource_type,
            resource_props=resource_properties,
            signal_type=_SIGNAL_TYPE,
        )
        hint = verdict.audit_hint
        if hint is None or hint.abstained_rule_ids:
            raise AssuranceTwinEvaluationUnavailableError(
                "Assurance Twin deterministic evaluation abstained"
            )
        if not hint.citing_rule_ids:
            raise AssuranceTwinEvaluationUnavailableError(
                "Assurance Twin Resource has no applicable Rule coverage"
            )
        if len(hint.evaluation_receipts) != len(hint.citing_rule_ids):
            raise AssuranceTwinEvaluationUnavailableError(
                "Assurance Twin deterministic evaluation receipts are incomplete"
            )
        _require_declared_inputs(
            rules_by_id=rules_by_id,
            rule_ids=hint.citing_rule_ids,
            resource=resource,
            properties=resource_properties,
        )
        receipt_by_rule = dict(zip(hint.citing_rule_ids, hint.evaluation_receipts, strict=True))
        evaluated.update(hint.citing_rule_ids)
        for rule_id, receipt in receipt_by_rule.items():
            coverage.append(
                {
                    "resource_type": resource.resource_type,
                    "resource_ref": resource.ref,
                    "rule_id": rule_id,
                    "receipt": asdict(receipt),
                }
            )
        for finding in verdict.findings:
            finding_receipt = receipt_by_rule.get(finding.rule_id)
            if finding_receipt is None:
                raise AssuranceTwinEvaluationUnavailableError(
                    "Assurance Twin finding has no exact Rule receipt"
                )
            reason = finding.context.get("deny_reason", "rule_denied")
            if not isinstance(reason, str) or not reason.strip():
                reason = "rule_denied"
            findings.append(
                Finding(
                    rule_id=finding.rule_id,
                    resource=ResourceRef(resource.resource_type, resource.ref),
                    severity=finding.severity.value,
                    reason=reason,
                    evidence_refs=(
                        finding_receipt.policy_source_digest,
                        finding_receipt.input_evidence_digest,
                        finding_receipt.result_digest,
                    ),
                )
            )
            if len(findings) > _MAX_FINDINGS:
                raise AssuranceTwinEvaluationUnavailableError(
                    "Assurance Twin findings exceed the exact projection bound"
                )

    evaluated_ids = tuple(sorted(evaluated))
    if not evaluated_ids or any(rule_id not in rules_by_id for rule_id in evaluated_ids):
        raise AssuranceTwinEvaluationUnavailableError(
            "Assurance Twin projection has no applicable complete Rule coverage"
        )
    rule_set_digest = _digest(
        [rules_by_id[rule_id].model_dump(mode="json") for rule_id in evaluated_ids]
    )
    evaluator_generation = engine.evaluator_generation_digest
    if evaluator_generation is None:
        raise AssuranceTwinEvaluationUnavailableError(
            "Assurance Twin evaluator generation is unavailable"
        )
    generation_digest = rule_generation_digest(
        rules,
        evaluator_generation_digest=evaluator_generation,
    )
    coverage_digest = _digest(coverage)
    ordered_findings = tuple(
        sorted(
            findings,
            key=lambda item: (
                -_SEVERITY_RANK[item.severity],
                item.rule_id,
                item.resource.resource_type,
                item.resource.ref,
            ),
        )
    )
    return CompletePostureEvaluation(
        findings=ordered_findings,
        evaluated_rule_ids=evaluated_ids,
        rule_set_digest=rule_set_digest,
        rule_generation_digest=generation_digest,
        rule_generation_time=rule_generation_time,
        coverage_refs=(inventory_revision, rule_set_digest, coverage_digest),
    )


def rule_generation_digest(
    rules: tuple[Rule, ...],
    *,
    evaluator_generation_digest: str,
) -> str:
    """Bind active Rule models and the immutable evaluator artifact generation."""

    return _digest(
        {
            "evaluator_generation_digest": evaluator_generation_digest,
            "rules": [
                rule.model_dump(mode="json") for rule in sorted(rules, key=lambda item: item.id)
            ],
        }
    )


def _require_declared_inputs(
    *,
    rules_by_id: dict[str, Rule],
    rule_ids: tuple[str, ...],
    resource: ResourceRef,
    properties: object,
) -> None:
    if not isinstance(properties, dict):
        raise AssuranceTwinEvaluationUnavailableError(
            "Assurance Twin Resource properties are unavailable"
        )
    for rule_id in rule_ids:
        rule = rules_by_id[rule_id]
        required_refs = {
            item for item in rule.evaluates if item != "*" and item.startswith("property.")
        }
        for criterion in rule.submission_criteria:
            if criterion.kind is SubmissionCriterionKind.LINK_EXISTS:
                raise AssuranceTwinEvaluationUnavailableError(
                    "Assurance Twin Rule requires unavailable relationship evidence"
                )
            if criterion.kind is SubmissionCriterionKind.PROPERTY_EXISTS:
                required_refs.add(criterion.value)
        prefix = f"property.{resource.resource_type}."
        for property_ref in required_refs:
            if not property_ref.startswith(prefix):
                raise AssuranceTwinEvaluationUnavailableError(
                    "Assurance Twin Rule property coverage does not match its Resource"
                )
            path = property_ref.removeprefix(prefix)
            if not _property_present(properties, path):
                raise AssuranceTwinEvaluationUnavailableError(
                    "Assurance Twin Rule input property is unavailable"
                )


def _property_present(properties: dict[str, object], path: str) -> bool:
    if path in properties:
        return properties[path] is not None
    current: object = properties
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    return current is not None


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _valid_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "AssuranceTwinEvaluationUnavailableError",
    "CompletePostureEvaluation",
    "evaluate_complete_posture",
    "rule_generation_digest",
]
