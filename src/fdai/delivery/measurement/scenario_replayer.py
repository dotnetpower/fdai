"""Frozen scenario replay adapter for scheduled regression measurement."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from fdai.core.control_loop import ControlLoop, ControlLoopOutcome
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import ResourceLockManager, ShadowExecutor, TemplateRenderer
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.measurement.regression import (
    GuardKind,
    GuardMetric,
    MeasurementSample,
    SuccessMetric,
)
from fdai.core.risk_gate import ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator, RuleIndex, T0Engine
from fdai.core.trust_router import TrustRouter
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher


class FrozenScenarioReplayer:
    """Replay enriched frozen scenarios through the shipped control loop."""

    def __init__(
        self,
        *,
        repo_root: Path,
        scenario_set_version: str,
        audit_store: StateStore,
        promotion_registry: ActionPromotionRegistry,
    ) -> None:
        self.scenario_set_version = scenario_set_version
        self._root = repo_root
        self._audit = audit_store
        self._registry = promotion_registry

    async def replay(self) -> tuple[MeasurementSample, ...]:
        loop, rules_by_id = self._build_loop()
        scenario_root = self._root / "tests" / "scenarios" / self.scenario_set_version
        enrichment_root = (
            self._root / "tests" / "scenarios" / "enrichment" / self.scenario_set_version
        )
        if not scenario_root.is_dir() or not enrichment_root.is_dir():
            raise FileNotFoundError(
                f"frozen scenarios or enrichment missing for {self.scenario_set_version}"
            )

        observations: dict[str, list[tuple[bool, bool, bool, bool]]] = defaultdict(list)
        replayed = 0
        for scenario_path in sorted(scenario_root.glob("*.json")):
            scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
            enrichment_path = enrichment_root / scenario_path.name
            if not enrichment_path.is_file():
                continue
            enrichment = json.loads(enrichment_path.read_text(encoding="utf-8"))
            event = dict(scenario["event"])
            payload = dict(event.get("payload") or {})
            payload["resource"] = enrichment["event_payload_resource"]
            event["payload"] = payload
            result = await loop.process(event)
            expected = scenario["expected"]
            expected_decision = str(expected["decision"])
            policy_escape = bool(expected["guard"]["should_trigger_policy_violation"]) and (
                result.decision == "auto"
            )
            rolled_back = bool(expected["guard"]["should_rollback"])
            for rule_id in result.citing_rule_ids:
                rule = rules_by_id.get(rule_id)
                if rule is None:
                    continue
                observations[rule.remediates].append(
                    (
                        result.decision == expected_decision,
                        policy_escape,
                        rolled_back,
                        result.outcome is ControlLoopOutcome.EXECUTED,
                    )
                )
            replayed += 1
        if replayed == 0 or not observations:
            raise RuntimeError("scenario replay produced no measurable action observations")

        samples: list[MeasurementSample] = []
        for action_type, rows in sorted(observations.items()):
            total = len(rows)
            correct = sum(1 for row in rows if row[0])
            escapes = sum(1 for row in rows if row[1])
            rollbacks = sum(1 for row in rows if row[2])
            executed = sum(1 for row in rows if row[3])
            samples.append(
                MeasurementSample(
                    action_type_id=action_type,
                    scenario_set_version=self.scenario_set_version,
                    guard_metrics=(
                        GuardMetric(
                            GuardKind.POLICY_VIOLATION_ESCAPE,
                            ceiling=0.0,
                            observed=float(escapes),
                        ),
                        GuardMetric(
                            GuardKind.ROLLBACK_RATE,
                            ceiling=0.05,
                            observed=rollbacks / total,
                        ),
                        GuardMetric(
                            GuardKind.FALSE_POSITIVE_RATE,
                            ceiling=0.1,
                            observed=1.0 - (correct / total),
                        ),
                    ),
                    success_metrics=(
                        SuccessMetric(
                            name="scenario_accuracy",
                            lower_ci=0.9,
                            observed=correct / total,
                        ),
                        SuccessMetric(
                            name="execution_share",
                            lower_ci=0.0,
                            observed=executed / total,
                        ),
                    ),
                )
            )
        return tuple(samples)

    def _build_loop(self) -> tuple[ControlLoop, dict[str, Any]]:
        catalog_root = self._root / "rule-catalog"
        registry = PackageResourceSchemaRegistry()
        action_types = load_ontology_catalog(
            catalog_root,
            schema_registry=registry,
        ).action_types
        vocabulary = load_resource_type_registry_from_mapping(
            yaml.safe_load(
                (catalog_root / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
            )
        )
        rules = load_rule_catalog(
            catalog_root / "catalog",
            schema_registry=registry,
            action_types=action_types,
            resource_types=vocabulary,
            policies_root=self._root / "policies",
            remediation_root=catalog_root / "remediation",
        )
        rules_by_id = {rule.id: rule for rule in rules}
        action_types_by_name = {item.name: item for item in action_types}
        index = RuleIndex.build(rules)
        validator = JsonSchemaEventValidator(JsonSchemaContractValidator(registry))
        loop = ControlLoop(
            event_ingest=EventIngest(validator=validator),
            trust_router=TrustRouter(index=index),
            t0_engine=T0Engine(
                index=index,
                evaluator=OpaRegoEvaluator(policies_root=self._root / "policies"),
            ),
            action_builder=ActionBuilder(action_types_by_name=action_types_by_name),
            executor=ShadowExecutor(
                publisher=RecordingRemediationPrPublisher(),
                audit_store=self._audit,
                renderer=TemplateRenderer(remediation_root=catalog_root / "remediation"),
                resource_lock=ResourceLockManager(),
            ),
            audit_store=self._audit,
            rules_by_id=rules_by_id,
            risk_table=load_risk_table(catalog_root / "risk-classification.yaml"),
            action_types_by_name=action_types_by_name,
            risk_gate=RiskGate(registry=self._registry),
            inventory_age_provider=_fresh_inventory,
        )
        return loop, rules_by_id


async def _fresh_inventory(_resource_ref: str) -> int:
    return 0


__all__ = ["FrozenScenarioReplayer"]
