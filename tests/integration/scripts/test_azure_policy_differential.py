from __future__ import annotations

import asyncio
import importlib.util
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator
from fdai.rule_catalog.pipeline.translate.azure_policy import load_alias_map, translate_policy
from fdai.shared.contracts.models import Rule

REPO_ROOT = Path(__file__).resolve().parents[3]
AKS = "Microsoft.ContainerService/managedClusters"


def _module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "deployment" / "local" / "run-azure-policy-differential.py"
    spec = importlib.util.spec_from_file_location("run_azure_policy_differential", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(tmp_path: Path) -> tuple[Rule, OpaRegoEvaluator]:
    definition: dict[str, Any] = {
        "name": "0a1b2c3d-synthetic-defender",
        "properties": {
            "displayName": "Defender profile",
            "mode": "Indexed",
            "version": "1.0.0",
            "parameters": {"effect": {"type": "String", "defaultValue": "Audit"}},
            "policyRule": {
                "if": {
                    "allOf": [
                        {"field": "type", "equals": AKS},
                        {
                            "field": f"{AKS}/securityProfile.defender.securityMonitoring.enabled",
                            "notEquals": True,
                        },
                    ]
                },
                "then": {"effect": "[parameters('effect')]"},
            },
        },
    }
    [result] = translate_policy(
        definition,
        alias_map=load_alias_map(REPO_ROOT / "rule-catalog/translation/azure-policy/aliases.yaml"),
        content_hash="sha256:" + "0" * 63 + "1",
        origin="Security Center/synthetic.json",
        resolved_ref="a" * 40,
        retrieved_at="2026-10-08T00:00:00Z",
    )
    rule = Rule.model_validate(result.rule)
    path = tmp_path / "policies" / rule.check_logic.reference.removeprefix("policies/")
    path.parent.mkdir(parents=True)
    path.write_text(result.rego)
    return rule, OpaRegoEvaluator(policies_root=tmp_path / "policies")


def test_scenarios_carry_compliance_expectations_without_resource_identity() -> None:
    module = _module()
    rule = type("R", (), {"id": "rule-x", "resource_type": "kubernetes-cluster"})()

    scenario = module._scenario(rule, 3, {"defender_security_monitoring_enabled": False}, True)

    assert scenario["expected"]["decision"] == "auto"
    assert scenario["expected"]["guard"]["should_trigger_policy_violation"] is True
    assert scenario["event"]["payload"]["resource"]["resource_id"] == (
        "kubernetes-cluster::rule-x-3"
    )


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not found")
def test_quality_gate_passes_only_when_the_candidate_agrees(tmp_path: Path) -> None:
    module = _module()
    rule, evaluator = _candidate(tmp_path)
    agreeing = [
        ({"defender_security_monitoring_enabled": False}, True),
        ({"defender_security_monitoring_enabled": True}, False),
    ]
    escaping = [({"defender_security_monitoring_enabled": True}, True)]

    passed = asyncio.run(module._quality_gate(rule, agreeing, evaluator))
    failed = asyncio.run(module._quality_gate(rule, escaping, evaluator))

    assert passed["regression_outcome"] == "pass"
    assert passed["policy_violation_escapes"] == 0
    assert failed["regression_outcome"] != "pass"
    assert failed["policy_violation_escapes"] == 1
