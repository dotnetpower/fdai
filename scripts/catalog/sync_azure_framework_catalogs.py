#!/usr/bin/env python3
"""Materialize the pinned Azure CAF/WAF framework and WAF checklist catalogs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = ROOT / "rule-catalog"
FRAMEWORK_ROOT = CATALOG_ROOT / "frameworks"
BEST_PRACTICE_ROOT = CATALOG_ROOT / "best-practices"
RULE_SET_ROOT = CATALOG_ROOT / "rule-sets"
RETRIEVED_AT = "2026-08-31T00:00:00Z"

WAF_SOURCES = {
    "reliability": {
        "source_url": "https://learn.microsoft.com/en-us/azure/well-architected/reliability/checklist",
        "source_version": "2026-05-29",
        "resolved_ref": "687e8febe6ddfa4646952220e057a50b1046a75a",
    },
    "security": {
        "source_url": "https://learn.microsoft.com/en-us/azure/well-architected/security/checklist",
        "source_version": "2026-06-26",
        "resolved_ref": "1df1c6023e01032c7be0013b086379c176827b1c",
    },
    "cost-optimization": {
        "source_url": "https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/checklist",
        "source_version": "2025-10-30",
        "resolved_ref": "28a78d22523542beeafc7de5eaa11fad791559b6",
    },
    "operational-excellence": {
        "source_url": "https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence/checklist",
        "source_version": "2026-06-11",
        "resolved_ref": "84fd234f106eacce573ee415497edd96436e6620",
    },
    "performance-efficiency": {
        "source_url": "https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency/checklist",
        "source_version": "2026-05-06",
        "resolved_ref": "ce3921ce25f18132fc642077a7e9edfc0fa69cc3",
    },
}


def requirement(kind: str, ref: str, freshness_days: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": kind, "ref": ref}
    if freshness_days is not None:
        value["freshness_days"] = freshness_days
    return value


def artifact(ref: str, days: int = 180) -> dict[str, Any]:
    return requirement("artifact", ref, days)


def metric(ref: str, days: int = 90) -> dict[str, Any]:
    return requirement("metric", ref, days)


def drill(ref: str, days: int = 180) -> dict[str, Any]:
    return requirement("drill", ref, days)


def approval(ref: str) -> dict[str, Any]:
    return requirement("approval", ref)


def rule(ref: str) -> dict[str, Any]:
    return requirement("rule", ref)


WAF_CONTROLS: dict[str, list[dict[str, Any]]] = {
    "reliability": [
        {
            "code": "RE:01",
            "title": "Focus workload design on simplicity and efficiency",
            "severity": "medium",
            "category": "reliability",
            "requirements": [
                artifact("target-architecture"),
                artifact("architecture-tradeoff-record"),
                approval("architecture-owner"),
            ],
        },
        {
            "code": "RE:02",
            "title": "Identify and rate user and system flows",
            "severity": "high",
            "category": "reliability",
            "requirements": [artifact("critical-flow-inventory"), approval("architecture-owner")],
        },
        {
            "code": "RE:03",
            "title": "Perform failure mode analysis",
            "severity": "high",
            "category": "reliability",
            "requirements": [artifact("failure-mode-analysis"), approval("reliability-owner")],
        },
        {
            "code": "RE:04",
            "title": "Define reliability and recovery targets",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                metric("workload-slo-approval"),
                metric("rpo-rto-approval", 180),
                approval("reliability-owner"),
            ],
        },
        {
            "code": "RE:05",
            "title": "Add redundancy for critical flows",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                rule("compute.vm-scale-set.zone-redundancy"),
                rule("cache.zone-redundant"),
                rule("kubernetes-node-pool.multi-zone"),
                rule("postgresql-server.high-availability"),
                rule("sql-database.zone-redundant"),
                artifact("critical-flow-redundancy-review"),
                approval("reliability-owner"),
            ],
        },
        {
            "code": "RE:06",
            "title": "Implement timely and reliable scaling",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("scaling-strategy"),
                metric("capacity-test-results"),
                approval("reliability-owner"),
            ],
        },
        {
            "code": "RE:07",
            "title": "Implement self-preservation and self-healing",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                rule("object-storage.soft-delete-blob"),
                rule("object-storage.versioning-enabled"),
                rule("secret-store.soft-delete.enabled"),
                drill("self-healing-validation", 90),
                approval("reliability-owner"),
            ],
        },
        {
            "code": "RE:08",
            "title": "Test resiliency and availability scenarios",
            "severity": "high",
            "category": "reliability",
            "requirements": [drill("reliability-test-results", 90), approval("reliability-owner")],
        },
        {
            "code": "RE:09",
            "title": "Implement tested disaster recovery plans",
            "severity": "critical",
            "category": "reliability",
            "requirements": [
                artifact("disaster-recovery-plan"),
                drill("restore-failover-drill"),
                metric("rpo-rto-approval", 180),
                approval("reliability-owner"),
            ],
        },
        {
            "code": "RE:10",
            "title": "Continuously measure and track system health",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                rule("kubernetes-cluster.diagnostic-settings-required"),
                rule("object-storage.diagnostic-settings-required"),
                rule("postgresql-server.diagnostic-settings-required"),
                rule("secret-store.diagnostic-settings-required"),
                rule("sql-database.diagnostic-settings-required"),
                metric("health-monitoring-evidence", 30),
                artifact("alerting-and-retention-review", 90),
                approval("operations-owner"),
            ],
        },
    ],
    "security": [
        {
            "code": "SE:01",
            "title": "Establish and continuously improve a security baseline",
            "severity": "critical",
            "category": "security",
            "requirements": [
                artifact("security-baseline"),
                metric("secure-score-snapshot", 90),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:02",
            "title": "Apply a secure development lifecycle",
            "severity": "critical",
            "category": "security",
            "requirements": [
                artifact("secure-development-lifecycle"),
                metric("security-scan-results", 30),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:03",
            "title": "Classify workload data and systems",
            "severity": "high",
            "category": "security",
            "requirements": [
                artifact("data-classification-inventory"),
                approval("data-owner"),
                approval("privacy-owner"),
            ],
        },
        {
            "code": "SE:04",
            "title": "Design intentional segmentation and perimeters",
            "severity": "critical",
            "category": "security",
            "requirements": [
                artifact("segmentation-design"),
                artifact("network-data-flow-validation", 90),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:05",
            "title": "Implement strict conditional and auditable identity and access management",
            "severity": "critical",
            "category": "security",
            "requirements": [
                rule("compute.vm.managed-identity.assigned"),
                rule("subscription.role-assignment.no-standing-privileged-access"),
                rule("subscription.role-assignment.no-guest-privileged"),
                rule("managed-identity.role-assignment.no-privileged-subscription-scope"),
                rule("managed-identity.role-assignment.no-wildcard-action"),
                artifact("identity-access-review", 90),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:06",
            "title": "Isolate filter and control network traffic",
            "severity": "critical",
            "category": "security",
            "requirements": [
                rule("network.nsg.no-inbound-any-rdp"),
                rule("network.nsg.no-inbound-any-ssh"),
                rule("object-storage.private-endpoint.required"),
                rule("secret-store.public-network-access.disabled"),
                artifact("network-data-flow-validation", 90),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:07",
            "title": "Encrypt data with modern methods",
            "severity": "critical",
            "category": "security",
            "requirements": [
                rule("object-storage.encryption-at-rest.required"),
                rule("object-storage.https-only.required"),
                rule("object-storage.min-tls-version"),
                rule("postgresql-server.encryption-at-rest"),
                rule("postgresql-server.ssl-enforcement"),
                rule("sql-database.tde-required"),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:08",
            "title": "Harden workload resources",
            "severity": "high",
            "category": "security",
            "requirements": [
                artifact("resource-hardening-baseline"),
                metric("configuration-compliance-report", 90),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:09",
            "title": "Protect and rotate application secrets",
            "severity": "critical",
            "category": "security",
            "requirements": [
                rule("secret-store.rotation-overdue"),
                rule("secret-store.rbac-authorization.enabled"),
                rule("secret-store.purge-protection.enabled"),
                artifact("secrets-management-plan"),
                drill("emergency-secret-rotation", 180),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:10",
            "title": "Implement holistic threat monitoring",
            "severity": "critical",
            "category": "security",
            "requirements": [
                artifact("security-monitoring-plan"),
                metric("threat-detection-evidence", 30),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:11",
            "title": "Establish comprehensive security testing",
            "severity": "critical",
            "category": "security",
            "requirements": [
                artifact("security-test-results", 90),
                drill("threat-detection-validation", 90),
                approval("security-owner"),
            ],
        },
        {
            "code": "SE:12",
            "title": "Define and test security incident response",
            "severity": "critical",
            "category": "security",
            "requirements": [
                artifact("incident-response-plan"),
                drill("incident-response-drill"),
                approval("security-owner"),
                approval("operations-owner"),
            ],
        },
    ],
    "cost-optimization": [
        {
            "code": "CO:01",
            "title": "Create a culture of financial responsibility",
            "severity": "medium",
            "category": "cost",
            "requirements": [
                artifact("financial-accountability-model"),
                artifact("cost-training-evidence"),
                approval("cost-owner"),
            ],
        },
        {
            "code": "CO:02",
            "title": "Create and maintain a cost model",
            "severity": "high",
            "category": "cost",
            "requirements": [
                artifact("workload-cost-model", 90),
                metric("cost-estimate-confirmation", 90),
                approval("cost-owner"),
            ],
        },
        {
            "code": "CO:03",
            "title": "Collect and review cost data",
            "severity": "high",
            "category": "cost",
            "requirements": [
                metric("daily-cost-report", 30),
                metric("budget-forecast-evidence", 30),
                approval("cost-owner"),
            ],
        },
        {
            "code": "CO:04",
            "title": "Set spending guardrails",
            "severity": "high",
            "category": "cost",
            "requirements": [
                artifact("spending-guardrails", 90),
                metric("budget-alert-validation", 90),
                approval("cost-owner"),
            ],
        },
        {
            "code": "CO:05",
            "title": "Obtain the best available provider rates",
            "severity": "medium",
            "category": "cost",
            "requirements": [artifact("rate-optimization-review", 180), approval("cost-owner")],
        },
        {
            "code": "CO:06",
            "title": "Align usage to billing increments",
            "severity": "medium",
            "category": "cost",
            "requirements": [metric("billing-increment-analysis", 90), approval("cost-owner")],
        },
        {
            "code": "CO:07",
            "title": "Optimize component costs",
            "severity": "high",
            "category": "cost",
            "requirements": [metric("component-cost-review", 30), approval("cost-owner")],
        },
        {
            "code": "CO:08",
            "title": "Optimize environment costs",
            "severity": "medium",
            "category": "cost",
            "requirements": [metric("environment-cost-review", 90), approval("cost-owner")],
        },
        {
            "code": "CO:09",
            "title": "Optimize flow costs",
            "severity": "medium",
            "category": "cost",
            "requirements": [metric("critical-flow-cost-analysis", 90), approval("cost-owner")],
        },
        {
            "code": "CO:10",
            "title": "Optimize data costs",
            "severity": "medium",
            "category": "cost",
            "requirements": [artifact("data-cost-optimization-review", 90), approval("cost-owner")],
        },
        {
            "code": "CO:11",
            "title": "Optimize code costs",
            "severity": "medium",
            "category": "cost",
            "requirements": [artifact("code-cost-review", 90), approval("cost-owner")],
        },
        {
            "code": "CO:12",
            "title": "Optimize scaling costs",
            "severity": "high",
            "category": "cost",
            "requirements": [metric("scaling-cost-analysis", 90), approval("cost-owner")],
        },
        {
            "code": "CO:13",
            "title": "Optimize personnel time",
            "severity": "medium",
            "category": "cost",
            "requirements": [metric("personnel-time-optimization", 90), approval("cost-owner")],
        },
        {
            "code": "CO:14",
            "title": "Consolidate resources and responsibility",
            "severity": "medium",
            "category": "cost",
            "requirements": [artifact("consolidation-review", 180), approval("cost-owner")],
        },
    ],
    "operational-excellence": [
        {
            "code": "OE:01",
            "title": "Define standard workload development and operating practices",
            "severity": "high",
            "category": "compliance",
            "requirements": [artifact("operational-practices"), approval("operations-owner")],
        },
        {
            "code": "OE:02",
            "title": "Standardize routine ad-hoc and emergency operations",
            "severity": "high",
            "category": "compliance",
            "requirements": [artifact("operations-task-standards"), approval("operations-owner")],
        },
        {
            "code": "OE:03",
            "title": "Formalize practices across the software development lifecycle",
            "severity": "high",
            "category": "compliance",
            "requirements": [artifact("development-practices"), approval("release-owner")],
        },
        {
            "code": "OE:04",
            "title": "Standardize development tools and quality processes",
            "severity": "high",
            "category": "compliance",
            "requirements": [artifact("development-quality-standards"), approval("release-owner")],
        },
        {
            "code": "OE:05",
            "title": "Use a standardized infrastructure-as-code approach",
            "severity": "high",
            "category": "config_drift",
            "requirements": [artifact("production-terraform-plan", 30), approval("release-owner")],
        },
        {
            "code": "OE:06",
            "title": "Build a predictable workload supply chain",
            "severity": "critical",
            "category": "compliance",
            "requirements": [
                artifact("signed-image-provenance", 30),
                metric("supply-chain-gate-results", 30),
                approval("release-owner"),
            ],
        },
        {
            "code": "OE:07",
            "title": "Design a workload monitoring stack",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                rule("kubernetes-cluster.diagnostic-settings-required"),
                rule("object-storage.diagnostic-settings-required"),
                rule("postgresql-server.diagnostic-settings-required"),
                rule("secret-store.diagnostic-settings-required"),
                rule("sql-database.diagnostic-settings-required"),
                metric("health-monitoring-evidence", 30),
                artifact("alerting-and-retention-review", 90),
                approval("operations-owner"),
            ],
        },
        {
            "code": "OE:08",
            "title": "Establish a structured incident management process",
            "severity": "critical",
            "category": "reliability",
            "requirements": [
                artifact("incident-response-plan"),
                drill("incident-response-drill"),
                approval("operations-owner"),
            ],
        },
        {
            "code": "OE:09",
            "title": "Adopt testing practices aligned with business objectives",
            "severity": "high",
            "category": "compliance",
            "requirements": [artifact("test-strategy-results", 90), approval("release-owner")],
        },
        {
            "code": "OE:10",
            "title": "Design reliable secure and maintainable automation",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("automation-safety-review"),
                metric("automation-reliability-results", 90),
                approval("operations-owner"),
            ],
        },
        {
            "code": "OE:11",
            "title": "Define safe deployment practices",
            "severity": "critical",
            "category": "reliability",
            "requirements": [
                artifact("deployment-and-rollback"),
                drill("smoke-canary-results", 30),
                approval("release-owner"),
            ],
        },
    ],
    "performance-efficiency": [
        {
            "code": "PE:01",
            "title": "Define numerical performance targets for workload flows",
            "severity": "high",
            "category": "reliability",
            "requirements": [metric("performance-targets", 90), approval("performance-owner")],
        },
        {
            "code": "PE:02",
            "title": "Conduct capacity planning before predicted demand changes",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("capacity-plan", 90),
                metric("capacity-test-results", 90),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:03",
            "title": "Select services and tiers that meet performance targets",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("service-selection-review"),
                approval("architecture-owner"),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:04",
            "title": "Establish consistent performance measurement",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                metric("performance-baseline", 30),
                metric("health-monitoring-evidence", 30),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:05",
            "title": "Optimize scaling and partitioning",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("scaling-partitioning-plan"),
                metric("capacity-test-results", 90),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:06",
            "title": "Test performance in a production-like environment",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("performance-test-results", 90),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:07",
            "title": "Optimize code and infrastructure",
            "severity": "medium",
            "category": "reliability",
            "requirements": [
                artifact("code-infrastructure-performance-review", 90),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:08",
            "title": "Optimize data usage and data-store performance",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("data-performance-review", 90),
                approval("data-owner"),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:09",
            "title": "Prioritize performance of critical flows",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("critical-flow-inventory"),
                metric("performance-targets", 90),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:10",
            "title": "Minimize operational task performance impact",
            "severity": "medium",
            "category": "reliability",
            "requirements": [
                artifact("maintenance-impact-plan", 90),
                approval("operations-owner"),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:11",
            "title": "Respond effectively to live performance issues",
            "severity": "high",
            "category": "reliability",
            "requirements": [
                artifact("performance-incident-runbook"),
                drill("performance-incident-drill", 180),
                approval("performance-owner"),
            ],
        },
        {
            "code": "PE:12",
            "title": "Continuously optimize deteriorating performance",
            "severity": "medium",
            "category": "reliability",
            "requirements": [metric("performance-trend-review", 30), approval("performance-owner")],
        },
    ],
}

CAF_CONTROLS = [
    (
        "strategy",
        "Strategy",
        "Define motivations, measurable outcomes, ownership, and strategic tradeoffs.",
    ),
    ("plan", "Plan", "Prepare people, skills, backlog, operating model, and adoption sequencing."),
    ("ready", "Ready", "Establish an Azure landing zone and shared platform foundation."),
    ("adopt", "Adopt", "Migrate, modernize, and build workloads through governed delivery."),
    (
        "govern",
        "Govern",
        "Assess risks, document guardrails, enforce policy, and monitor compliance.",
    ),
    (
        "secure",
        "Secure",
        "Apply Zero Trust, incident readiness, CIA safeguards, and posture "
        "sustainment across phases.",
    ),
    (
        "manage",
        "Manage",
        "Operate through the Ready, Administer, Monitor, and Protect responsibilities.",
    ),
    (
        "landing-zone.billing-tenant",
        "Landing zone: billing and tenant",
        "Structure billing and tenant foundations deliberately.",
    ),
    (
        "landing-zone.identity-access",
        "Landing zone: identity and access",
        "Use identity as the primary security boundary.",
    ),
    (
        "landing-zone.resource-organization",
        "Landing zone: resource organization",
        "Design management groups, subscriptions, and resource organization.",
    ),
    (
        "landing-zone.network-connectivity",
        "Landing zone: network topology and connectivity",
        "Define connectivity and network security boundaries.",
    ),
    (
        "landing-zone.security",
        "Landing zone: security",
        "Implement controls and processes that protect the cloud environment.",
    ),
    (
        "landing-zone.management",
        "Landing zone: management",
        "Provide visibility, operational compliance, protection, and recovery.",
    ),
    (
        "landing-zone.governance",
        "Landing zone: governance",
        "Automate policy auditing and enforcement.",
    ),
    (
        "landing-zone.platform-automation-devops",
        "Landing zone: platform automation and DevOps",
        "Use governed tools and templates for platform deployment.",
    ),
]

CAF_SOURCES = {
    "overview": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/overview",
        "2026-08-27",
        "9e9db6f427b04cccdc3040b31aaf3440eaf5b994",
    ),
    "strategy": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/strategy/",
        "2026-05-19",
        "f01c1dab5d89efad6e7f4b54739d8c03ba6b4545",
    ),
    "plan": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/plan/prepare-organization-for-cloud",
        "2026-04-07",
        "67c4c4dcec8a6e24c28b34342d46e5b3cfea0e5d",
    ),
    "ready": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/landing-zone/",
        "2026-08-26",
        "5c260b3f1e0676826d514a018b5c4226da1b29a1",
    ),
    "adopt": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/migrate/plan-migration",
        "2026-03-25",
        "bb4d2f198b2cb6b4a67449bf01922b43784d3757",
    ),
    "govern": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/govern/build-cloud-governance-team",
        "2026-03-09",
        "082e3bf69bd3a5045d8c51c47774d15ec01642e1",
    ),
    "secure": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/secure/overview",
        "2026-01-05",
        "d139382c5522f77ab28cbbeddbbc517064f5ff8c",
    ),
    "manage": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/manage/ready-cloud-operations",
        "2026-04-07",
        "9454caeefed88e57d5134e2bd25738b3b8dc967b",
    ),
    "landing-zone": (
        "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/landing-zone/design-areas",
        "2025-12-19",
        "7ad494e8e4d704b4e89be8091979fe80c0281a8d",
    ),
}

WAF_RULE_SETS = {
    "reliability": [
        "cache.zone-redundant",
        "compute.vm-scale-set.zone-redundancy",
        "disk.snapshot-policy.required",
        "kubernetes-cluster.diagnostic-settings-required",
        "kubernetes-node-pool.multi-zone",
        "object-storage.diagnostic-settings-required",
        "object-storage.soft-delete-blob",
        "object-storage.versioning-enabled",
        "postgresql-server.diagnostic-settings-required",
        "postgresql-server.high-availability",
        "postgresql-server.point-in-time-restore",
        "secret-store.diagnostic-settings-required",
        "secret-store.soft-delete.enabled",
        "sql-database.diagnostic-settings-required",
        "sql-database.geo-redundant-backup",
        "sql-database.zone-redundant",
    ],
    "security": [
        "compute.vm.managed-identity.assigned",
        "managed-identity.role-assignment.no-privileged-subscription-scope",
        "managed-identity.role-assignment.no-wildcard-action",
        "network.nsg.no-inbound-any-rdp",
        "network.nsg.no-inbound-any-ssh",
        "object-storage.encryption-at-rest.required",
        "object-storage.https-only.required",
        "object-storage.min-tls-version",
        "object-storage.private-endpoint.required",
        "object-storage.public-access.deny",
        "object-storage.shared-key-access.disabled",
        "postgresql-server.encryption-at-rest",
        "postgresql-server.ssl-enforcement",
        "secret-store.public-network-access.disabled",
        "secret-store.purge-protection.enabled",
        "secret-store.rbac-authorization.enabled",
        "secret-store.rotation-overdue",
        "sql-database.audit-enabled",
        "sql-database.tde-required",
        "subscription.role-assignment.no-guest-privileged",
        "subscription.role-assignment.no-standing-privileged-access",
    ],
    "cost-optimization": [
        "object-storage.cost-center-tag.required",
        "resource-group.cost-center-tag.required",
    ],
    "operational-excellence": [
        "kubernetes-cluster.diagnostic-settings-required",
        "object-storage.diagnostic-settings-required",
        "ops.change-summary",
        "postgresql-server.diagnostic-settings-required",
        "resource-group.environment-tag.required",
        "resource-group.owner-tag.required",
        "resource-group.role-assignment.owner-count-within-limit",
        "secret-store.diagnostic-settings-required",
        "sql-database.diagnostic-settings-required",
    ],
    "performance-efficiency": [
        "cache.zone-redundant",
        "compute.vm-scale-set.zone-redundancy",
        "kubernetes-node-pool.multi-zone",
        "postgresql-server.high-availability",
        "sql-database.zone-redundant",
    ],
}


def _slug(code: str) -> str:
    return code.lower().replace(":", "-")


def _best_practice(pillar: str, control: dict[str, Any]) -> dict[str, Any]:
    source = WAF_SOURCES[pillar]
    return {
        "schema_version": "1.0.0",
        "kind": "best-practice",
        "id": f"azure-waf.{pillar}.{_slug(control['code'])}",
        "version": "1.0.0",
        "framework": "azure-waf",
        "control_id": control["code"],
        "title": control["title"],
        "rationale": f"Current evidence is required to assess {control['title'].lower()}.",
        "severity": control["severity"],
        "category": control["category"],
        "requirement_mode": "all",
        "requirements": control["requirements"],
        "provenance": {
            **source,
            "content_hash": f"git:{source['resolved_ref']}",
            "license": "CC-BY-4.0",
            "redistribution": "embeddable",
            "retrieved_at": RETRIEVED_AT,
            "mapped_by": "catalog-team",
        },
    }


def _waf_manifest() -> dict[str, Any]:
    areas = []
    for pillar, controls in WAF_CONTROLS.items():
        source = WAF_SOURCES[pillar]
        areas.append(
            {
                "id": pillar,
                **source,
                "retrieved_at": RETRIEVED_AT,
                "controls": [
                    {
                        "id": control["code"],
                        "title": control["title"],
                        "best_practice_ref": f"azure-waf.{pillar}.{_slug(control['code'])}@1.0.0",
                        "objective_refs": (
                            ["reliability.node-pool.zone-failure-tolerance@1.0.0"]
                            if control["code"] == "RE:05"
                            else []
                        ),
                        "mapping_status": "best_practice",
                    }
                    for control in controls
                ],
            }
        )
    return {
        "schema_version": "1.0.0",
        "kind": "framework-definition",
        "id": "azure-waf",
        "version": "2026-08-31",
        "name": "Azure Well-Architected Framework",
        "scope": "workload",
        "advisory": True,
        "completeness_scope": (
            "All coded recommendations on the five pinned design review checklist pages."
        ),
        "areas": areas,
    }


def _caf_manifest() -> dict[str, Any]:
    controls = []
    for control_id, title, description in CAF_CONTROLS:
        source_id = "landing-zone" if control_id.startswith("landing-zone.") else control_id
        source_url, source_version, resolved_ref = CAF_SOURCES[source_id]
        controls.append(
            {
                "id": control_id,
                "title": title,
                "description": description,
                "source_url": source_url,
                "source_version": source_version,
                "resolved_ref": resolved_ref,
                "retrieved_at": RETRIEVED_AT,
                "best_practice_ref": None,
                "objective_refs": [],
                "mapping_status": "reference_only",
                "applicability": "deployment_review_required",
            }
        )
    return {
        "schema_version": "1.0.0",
        "kind": "framework-definition",
        "id": "azure-caf",
        "version": "2026-08-31",
        "name": "Microsoft Cloud Adoption Framework for Azure",
        "scope": "cloud-estate",
        "advisory": True,
        "completeness_scope": (
            "Seven adoption methodologies and eight Azure landing-zone design areas; "
            "prose guidance remains living and context dependent."
        ),
        "sources": [
            {
                "id": source_id,
                "source_url": value[0],
                "source_version": value[1],
                "resolved_ref": value[2],
                "retrieved_at": RETRIEVED_AT,
            }
            for source_id, value in CAF_SOURCES.items()
        ],
        "controls": controls,
    }


def _rule_set(pillar: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "kind": "rule-set",
        "id": f"azure-waf.{pillar}",
        "version": "1.0.0",
        "members": [{"rule_id": rule_id, "version": "1.0.0"} for rule_id in WAF_RULE_SETS[pillar]],
        "provenance": {
            "created_at": RETRIEVED_AT,
            "created_by": "catalog-team",
            "source": "azure-waf",
        },
    }


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def main() -> None:
    expected_paths: set[Path] = set()
    for pillar, controls in WAF_CONTROLS.items():
        for control in controls:
            path = BEST_PRACTICE_ROOT / f"azure-waf.{pillar}.{_slug(control['code'])}.yaml"
            _write_yaml(path, _best_practice(pillar, control))
            expected_paths.add(path)
    for path in BEST_PRACTICE_ROOT.glob("azure-waf.*.yaml"):
        if path not in expected_paths:
            path.unlink()
    _write_yaml(FRAMEWORK_ROOT / "azure-waf.yaml", _waf_manifest())
    _write_yaml(FRAMEWORK_ROOT / "azure-caf.yaml", _caf_manifest())
    for pillar in WAF_RULE_SETS:
        _write_yaml(RULE_SET_ROOT / f"azure-waf.{pillar}.yaml", _rule_set(pillar))
    print(
        f"materialized {len(expected_paths)} WAF controls, 5 rule sets, and 2 framework definitions"
    )


if __name__ == "__main__":
    main()
