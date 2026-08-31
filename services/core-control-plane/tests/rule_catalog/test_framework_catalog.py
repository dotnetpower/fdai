from __future__ import annotations

from pathlib import Path

from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.shared.contracts.models import RequirementKind

ROOT = Path(__file__).resolve().parents[4]
CATALOG = ROOT / "rule-catalog"
OBJECTIVE_REF = "reliability.node-pool.zone-failure-tolerance@1.0.0"


def _known_refs() -> dict[RequirementKind, set[str]]:
    rule_ids = {path.stem for path in (CATALOG / "catalog").glob("*.yaml")}
    evidence_ids = {
        "alerting-and-retention-review",
        "architecture-tradeoff-record",
        "automation-reliability-results",
        "automation-safety-review",
        "billing-increment-analysis",
        "budget-alert-validation",
        "budget-forecast-evidence",
        "capacity-plan",
        "capacity-test-results",
        "code-cost-review",
        "code-infrastructure-performance-review",
        "component-cost-review",
        "configuration-compliance-report",
        "consolidation-review",
        "cost-estimate-confirmation",
        "cost-training-evidence",
        "critical-flow-cost-analysis",
        "critical-flow-inventory",
        "critical-flow-redundancy-review",
        "daily-cost-report",
        "data-classification-inventory",
        "data-cost-optimization-review",
        "data-performance-review",
        "deployment-and-rollback",
        "development-practices",
        "development-quality-standards",
        "disaster-recovery-plan",
        "emergency-secret-rotation",
        "environment-cost-review",
        "failure-mode-analysis",
        "financial-accountability-model",
        "health-monitoring-evidence",
        "identity-access-review",
        "incident-response-drill",
        "incident-response-plan",
        "maintenance-impact-plan",
        "network-data-flow-validation",
        "operational-practices",
        "operations-task-standards",
        "performance-baseline",
        "performance-incident-drill",
        "performance-incident-runbook",
        "performance-targets",
        "performance-test-results",
        "performance-trend-review",
        "personnel-time-optimization",
        "production-terraform-plan",
        "rate-optimization-review",
        "reliability-test-results",
        "resource-hardening-baseline",
        "restore-failover-drill",
        "rpo-rto-approval",
        "scaling-cost-analysis",
        "scaling-partitioning-plan",
        "scaling-strategy",
        "secrets-management-plan",
        "secure-development-lifecycle",
        "secure-score-snapshot",
        "security-baseline",
        "security-monitoring-plan",
        "security-scan-results",
        "security-test-results",
        "segmentation-design",
        "self-healing-validation",
        "service-selection-review",
        "signed-image-provenance",
        "smoke-canary-results",
        "spending-guardrails",
        "supply-chain-gate-results",
        "target-architecture",
        "test-strategy-results",
        "threat-detection-evidence",
        "threat-detection-validation",
        "workload-cost-model",
        "workload-slo-approval",
    }
    owners = {
        "architecture-owner",
        "cost-owner",
        "data-owner",
        "operations-owner",
        "performance-owner",
        "privacy-owner",
        "release-owner",
        "reliability-owner",
        "security-owner",
    }
    return {
        RequirementKind.RULE: rule_ids,
        RequirementKind.PROBE: set(),
        RequirementKind.ARTIFACT: evidence_ids,
        RequirementKind.METRIC: evidence_ids,
        RequirementKind.DRILL: evidence_ids,
        RequirementKind.APPROVAL: owners,
    }


def test_shipped_framework_catalog_is_complete_and_cross_referenced() -> None:
    best_practices = load_best_practice_catalog(
        CATALOG / "best-practices",
        known_refs=_known_refs(),
    )
    frameworks = load_framework_catalog(
        CATALOG / "frameworks",
        best_practices=best_practices,
        objective_refs=frozenset({OBJECTIVE_REF}),
        additional_roots=(CATALOG / "collected/wara-aprl",),
    )

    by_id = {item.id: item for item in frameworks}
    waf = by_id["azure-waf"]
    caf = by_id["azure-caf"]
    wara = by_id["azure-wara"]
    assert len(waf.resolved_controls()) == 59
    assert len(caf.resolved_controls()) == 15
    assert len(wara.resolved_controls()) == 456
    assert wara.inventory is not None
    assert wara.inventory.active_controls == 393
    assert wara.inventory.disabled_controls == 63
    assert wara.inventory.area_count == 83
    assert wara.inventory.resource_type_count == 80
    assert wara.inventory.automated_active_controls == 143
    assert wara.inventory.product_group_verified_active_controls == 276
    assert wara.inventory.published_active_digest == (
        "sha256:8547696168b33491cb8d4a677e961026bc22e866db5943289327f60b7a91a290"
    )
    assert wara.inventory.source_set_digest == (
        "sha256:a8ae8a25ec563bb361da705d1a9a85c74ed990b42b762e009cc3f0b2577df8f2"
    )
    assert {item.control.id[:2] for item in waf.resolved_controls()} == {
        "CO",
        "OE",
        "PE",
        "RE",
        "SE",
    }
    assert all(item.control.best_practice_ref is None for item in caf.resolved_controls())
    assert all(item.control.wara is not None for item in wara.resolved_controls())
    assert {
        item.control.wara.state
        for item in wara.resolved_controls()
        if item.control.wara is not None
    } == {"Active", "Disabled"}
