"""Deterministic O3 validation over frozen scenarios and reviewed catalogs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from fdai.core.operational_learning import (
    CatalogCheckReceipts,
    CatalogValidationRequest,
    PolicyCheckReceipt,
    ReplayCheckReceipt,
    SchemaCheckReceipt,
    ShadowCheckReceipt,
)
from fdai.core.tiers.t0_deterministic.engine import PolicyEvaluator
from fdai.rule_catalog.pipeline import (
    RegressionGate,
    RegressionOutcome,
    ShadowEvalReport,
    ShadowEvaluator,
)
from fdai.rule_catalog.schema.rule import load_rule_from_mapping
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.contracts.registry import SchemaRegistry


class DeterministicCatalogValidator:
    """Validate an O3 candidate without granting catalog or action authority.

    The validator uses one immutable scenario snapshot, replays the complete
    candidate twice, and compares the candidate with the reviewed baseline.
    Any schema, replay, regression, or policy failure produces a failed receipt
    that the core compiler quarantines.
    """

    def __init__(
        self,
        *,
        schema_registry: SchemaRegistry,
        action_type_names: frozenset[str],
        resource_type_ids: frozenset[str],
        baseline_rules: tuple[Rule, ...],
        scenarios: tuple[dict[str, Any], ...],
        scenario_set_id: str,
        replay_version: str,
        policy_version: str,
        evaluator: PolicyEvaluator | None = None,
        regression_gate: RegressionGate | None = None,
    ) -> None:
        if not scenario_set_id or not replay_version or not policy_version:
            raise ValueError("catalog validation versions MUST be non-empty")
        self._schema_registry = schema_registry
        self._action_type_names = set(action_type_names)
        self._resource_type_ids = set(resource_type_ids)
        self._baseline_rules = baseline_rules
        self._scenario_json = tuple(_canonical_json(scenario) for scenario in scenarios)
        self._scenario_set_id = scenario_set_id
        self._replay_version = replay_version
        self._policy_version = policy_version
        self._evaluator = evaluator
        self._regression_gate = regression_gate or RegressionGate()

    def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
        action_type_names = set(self._action_type_names)
        if request.draft_action_type is not None:
            action_type = OntologyActionType.model_validate(request.draft_action_type.mapping)
            action_type_names.add(action_type.name)
        draft_rule = load_rule_from_mapping(
            request.draft_rule.mapping,
            schema_registry=self._schema_registry,
            action_type_names=action_type_names,
            resource_type_ids=self._resource_type_ids,
            origin="operational-catalog-review",
        )
        candidate_rules = _replace_rule(self._baseline_rules, draft_rule)
        scenarios = self._scenarios()
        baseline = ShadowEvaluator(
            candidate_rules=self._baseline_rules,
            evaluator=self._evaluator,
        ).evaluate_scenarios(
            scenario_set_id=f"{self._scenario_set_id}::baseline",
            scenarios=scenarios,
        )
        first = ShadowEvaluator(
            candidate_rules=candidate_rules,
            evaluator=self._evaluator,
        ).evaluate_scenarios(
            scenario_set_id=self._scenario_set_id,
            scenarios=scenarios,
        )
        second = ShadowEvaluator(
            candidate_rules=candidate_rules,
            evaluator=self._evaluator,
        ).evaluate_scenarios(
            scenario_set_id=self._scenario_set_id,
            scenarios=scenarios,
        )
        baseline_digest = _report_digest(baseline)
        first_digest = _report_digest(first)
        second_digest = _report_digest(second)
        regression = self._regression_gate.evaluate(candidate=first, baseline=baseline)
        replay_passed = first_digest == second_digest
        policy_passed = first.policy_violation_escapes == 0
        common = {
            "candidate_digest": request.candidate.digest,
            "artifact_digest": request.artifact_digest,
        }
        return CatalogCheckReceipts(
            schema=SchemaCheckReceipt(
                **common,
                schema_version=request.schema_version,
                passed=True,
            ),
            replay=ReplayCheckReceipt(
                **common,
                replay_version=self._replay_version,
                first_result_digest=first_digest,
                second_result_digest=second_digest,
                passed=replay_passed,
            ),
            shadow=ShadowCheckReceipt(
                **common,
                scenario_set_id=self._scenario_set_id,
                baseline_result_digest=baseline_digest,
                challenger_result_digest=first_digest,
                regression_passed=regression.outcome is RegressionOutcome.PASS,
                policy_escapes=first.policy_violation_escapes,
                passed=(regression.outcome is RegressionOutcome.PASS and replay_passed),
            ),
            policy=PolicyCheckReceipt(
                **common,
                policy_version=self._policy_version,
                policy_escapes=first.policy_violation_escapes,
                passed=policy_passed,
            ),
        )

    def _scenarios(self) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(item) for item in self._scenario_json)


def _replace_rule(baseline: tuple[Rule, ...], draft: Rule) -> tuple[Rule, ...]:
    retained = tuple(rule for rule in baseline if rule.id != draft.id)
    return tuple(sorted((*retained, draft), key=lambda rule: rule.id))


def _report_digest(report: ShadowEvalReport) -> str:
    return hashlib.sha256(_canonical_json(asdict(report)).encode()).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


__all__ = ["DeterministicCatalogValidator"]
