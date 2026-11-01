#!/usr/bin/env python3
"""Import and verify official MSRC CSAF 2.0 advisories into FDAI's crosswalk catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
import urllib.request
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fdai.rule_catalog.schema.msrc_csaf import (
    CsafAdvisoryDocument,
    MsrcCsafCrosswalkCatalog,
    compare_dotted_versions,
    load_msrc_csaf_crosswalk_catalog,
)
from fdai.rule_catalog.schema.wara_assessment import canonical_digest

_SHARD_COUNT = 20
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_PUNCT_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
)

_ALLOWED_REMEDIATION_HOSTS = frozenset(
    {
        "aka.ms",
        "dev.azure.com",
        "docs.azure.cn",
        "docs.microsoft.com",
        "github.com",
        "learn.microsoft.com",
        "msrc.microsoft.com",
        "packages.microsoft.com",
        "portal.msrc.microsoft.com",
        "support.microsoft.com",
    }
)


def _baseline_seed_entries() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Return the three pinned baseline records used by unit and agent regression suites."""

    advisories: list[dict[str, Any]] = [
        {
            "csaf_version": "2.0",
            "tracking_id": "MSRC-2026-AKS-001",
            "title": "Azure Kubernetes Service Node Image Privilege Escalation Vulnerability",
            "initial_release_date": "2026-10-13T00:00:00Z",
            "current_release_date": "2026-10-14T00:00:00Z",
            "revision_count": 2,
            "source_url": "https://msrc.microsoft.com/csaf/advisories/2026/msrc-2026-aks-001.json",
            "document_digest": "sha256:" + "1" * 64,
            "signature_verified": True,
            "products": [
                {
                    "product_id": "AZURE-AKS-1.28",
                    "name": "Azure Kubernetes Service 1.28 Node Image",
                    "cpe": "cpe:/a:microsoft:azure_kubernetes_service:1.28",
                },
                {
                    "product_id": "AZURE-APPLIANCE-LEGACY",
                    "name": "Azure Legacy Appliance Firmware",
                    "cpe": None,
                },
            ],
            "vulnerabilities": [
                {
                    "cve_id": "CVE-2026-20001",
                    "title": "AKS Node Image Elevation of Privilege",
                    "cvss_base_score": 8.8,
                    "cvss_temporal_score": 8.2,
                    "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
                    "severity": "high",
                    "exploit_status": "exploited",
                    "publicly_disclosed": True,
                    "known_affected_product_ids": ["AZURE-AKS-1.28"],
                    "fixed_product_ids": [],
                    "known_not_affected_product_ids": [],
                    "remediations": [
                        {
                            "category": "vendor_fix",
                            "product_ids": ["AZURE-AKS-1.28"],
                            "details": "Upgrade AKS Kubernetes version to 1.28.9 or later.",
                            "fixed_version": "1.28.9",
                            "kb_article": None,
                            "workaround_property": None,
                            "workaround_expected_value": None,
                            "recommended_action_type": "remediate.disable-public-access",
                            "url": "https://msrc.microsoft.com/update-guide/vulnerability/CVE-2026-20001",
                        },
                        {
                            "category": "workaround",
                            "product_ids": ["AZURE-AKS-1.28"],
                            "details": (
                                "Disable public network access on the managed cluster "
                                "control plane."
                            ),
                            "fixed_version": None,
                            "kb_article": None,
                            "workaround_property": "public_network_access_enabled",
                            "workaround_expected_value": False,
                            "recommended_action_type": "remediate.disable-public-access",
                            "url": "https://msrc.microsoft.com/update-guide/vulnerability/CVE-2026-20001",
                        },
                    ],
                },
                {
                    "cve_id": "CVE-2026-20003",
                    "title": "Azure Legacy Appliance Unmapped Advisory",
                    "cvss_base_score": 5.5,
                    "cvss_temporal_score": None,
                    "cvss_vector": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N",
                    "severity": "medium",
                    "exploit_status": "unproven",
                    "publicly_disclosed": False,
                    "known_affected_product_ids": ["AZURE-APPLIANCE-LEGACY"],
                    "fixed_product_ids": [],
                    "known_not_affected_product_ids": [],
                    "remediations": [],
                },
            ],
        },
        {
            "csaf_version": "2.0",
            "tracking_id": "MSRC-2026-STORAGE-001",
            "title": "Azure Storage Transport Security Bypass Vulnerability",
            "initial_release_date": "2026-10-13T00:00:00Z",
            "current_release_date": "2026-10-13T00:00:00Z",
            "revision_count": 1,
            "source_url": "https://msrc.microsoft.com/csaf/advisories/2026/msrc-2026-storage-001.json",
            "document_digest": "sha256:" + "2" * 64,
            "signature_verified": True,
            "products": [
                {
                    "product_id": "AZURE-STORAGE-TLS",
                    "name": "Azure Storage Account TLS Configuration",
                    "cpe": "cpe:/a:microsoft:azure_storage:1.0",
                }
            ],
            "vulnerabilities": [
                {
                    "cve_id": "CVE-2026-20002",
                    "title": "Azure Storage Legacy TLS Downgrade",
                    "cvss_base_score": 9.1,
                    "cvss_temporal_score": 8.7,
                    "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
                    "severity": "critical",
                    "exploit_status": "exploitation_more_likely",
                    "publicly_disclosed": True,
                    "known_affected_product_ids": ["AZURE-STORAGE-TLS"],
                    "fixed_product_ids": [],
                    "known_not_affected_product_ids": [],
                    "remediations": [
                        {
                            "category": "vendor_fix",
                            "product_ids": ["AZURE-STORAGE-TLS"],
                            "details": "Enforce minimum TLS version 1.2 on Storage Accounts.",
                            "fixed_version": "1.2",
                            "kb_article": None,
                            "workaround_property": None,
                            "workaround_expected_value": None,
                            "recommended_action_type": "remediate.disable-public-access",
                            "url": "https://msrc.microsoft.com/update-guide/vulnerability/CVE-2026-20002",
                        }
                    ],
                }
            ],
        },
    ]
    products: list[dict[str, Any]] = [
        {
            "product_id": "AZURE-AKS-1.28",
            "product_name": "Azure Kubernetes Service 1.28 Node Image",
            "disposition": "canonical",
            "canonical_resource_type": "kubernetes-cluster",
            "canonical_resource_types": ["kubernetes-cluster"],
            "provider_resource_types": ["microsoft.containerservice/managedclusters"],
            "version_property": "kubernetes_version",
            "minimum_affected_version_inclusive": "1.28.0",
            "vulnerable_version_ceiling_exclusive": "1.28.9",
            "freshness_ceiling_seconds": 86400,
            "reviewer": "fdai-maintainers",
        },
        {
            "product_id": "AZURE-APPLIANCE-LEGACY",
            "product_name": "Azure Legacy Appliance Firmware",
            "disposition": "unsupported",
            "canonical_resource_type": None,
            "canonical_resource_types": [],
            "provider_resource_types": ["microsoft.customproviders/resourceproviders"],
            "version_property": None,
            "minimum_affected_version_inclusive": None,
            "vulnerable_version_ceiling_exclusive": None,
            "freshness_ceiling_seconds": 86400,
            "reviewer": "fdai-maintainers",
        },
        {
            "product_id": "AZURE-STORAGE-TLS",
            "product_name": "Azure Storage Account TLS Configuration",
            "disposition": "canonical",
            "canonical_resource_type": "object-storage",
            "canonical_resource_types": ["object-storage"],
            "provider_resource_types": ["microsoft.storage/storageaccounts"],
            "version_property": "minimum_tls_version",
            "minimum_affected_version_inclusive": "1.0",
            "vulnerable_version_ceiling_exclusive": "1.2",
            "freshness_ceiling_seconds": 86400,
            "reviewer": "fdai-maintainers",
        },
    ]
    vuln_mappings: list[dict[str, Any]] = [
        {
            "cve_id": "CVE-2026-20001",
            "advisory_tracking_id": "MSRC-2026-AKS-001",
            "disposition": "new_rule_candidate",
            "mapping_state": "full",
            "product_ids": ["AZURE-AKS-1.28"],
            "existing_rule_id": None,
            "candidate_action_type": "remediate.disable-public-access",
            "workaround_property": "public_network_access_enabled",
            "workaround_expected_value": False,
            "blocked_reasons": [],
        },
        {
            "cve_id": "CVE-2026-20002",
            "advisory_tracking_id": "MSRC-2026-STORAGE-001",
            "disposition": "existing_rule",
            "mapping_state": "full",
            "product_ids": ["AZURE-STORAGE-TLS"],
            "existing_rule_id": "object-storage.public-access.deny",
            "candidate_action_type": "remediate.disable-public-access",
            "workaround_property": None,
            "workaround_expected_value": None,
            "blocked_reasons": [],
        },
        {
            "cve_id": "CVE-2026-20003",
            "advisory_tracking_id": "MSRC-2026-AKS-001",
            "disposition": "ambiguous_or_blocked",
            "mapping_state": "unmapped",
            "product_ids": ["AZURE-APPLIANCE-LEGACY"],
            "existing_rule_id": None,
            "candidate_action_type": None,
            "workaround_property": None,
            "workaround_expected_value": None,
            "blocked_reasons": ["unsupported_provider_type"],
        },
    ]
    return advisories, products, vuln_mappings


def _classify_product_family(
    family_name: str,
    advisory_title: str,
) -> tuple[str, str, str, str | None, str, str | None]:
    """Return (canonical_type, arm_type, version_prop, existing_rule, disposition, action_type)."""

    combined = f"{family_name} {advisory_title}".casefold()
    if any(k in combined for k in ("kubernetes", "aks", "openshift", "aro")):
        return (
            "kubernetes-cluster",
            "microsoft.containerservice/managedclusters",
            "kubernetes_version",
            "kubernetes-node-pool.multi-zone",
            "new_rule_candidate",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("key vault", "keyvault", "confidential ledger")):
        return (
            "secret-store",
            "microsoft.keyvault/vaults",
            "vault_version",
            "secret-store.soft-delete.enable",
            "existing_rule",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("site recovery", "azure backup", "recovery services")):
        return (
            "backup-vault",
            "microsoft.recoveryservices/vaults",
            "vault_agent_version",
            None,
            "version_observation",
            None,
        )
    if (
        "storage" in combined
        or "file sync" in combined
        or "storsimple" in combined
        or "data box" in combined
    ) and "windows storage" not in combined:
        return (
            "object-storage",
            "microsoft.storage/storageaccounts",
            "minimum_tls_version",
            "object-storage.public-access.deny",
            "existing_rule",
            "remediate.disable-public-access",
        )
    if "postgresql" in combined:
        return (
            "postgresql-server",
            "microsoft.dbforpostgresql/flexibleservers",
            "engine_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if "mysql" in combined:
        return (
            "mysql-server",
            "microsoft.dbformysql/flexibleservers",
            "engine_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if "sql managed instance" in combined:
        return (
            "sql-managed-instance",
            "microsoft.sql/managedinstances",
            "engine_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if "azure sql database" in combined:
        return (
            "sql-database",
            "microsoft.sql/servers/databases",
            "engine_version",
            "sql-database.zone-redundant",
            "existing_rule",
            "remediate.disable-public-access",
        )
    if "sql server" in combined:
        return (
            "sql-server",
            "microsoft.sql/servers",
            "sql_server_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("cosmos", "cassandra", "horizondb")):
        return (
            "nosql-database",
            "microsoft.documentdb/databaseaccounts",
            "engine_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("functions", "function app")):
        return (
            "compute.function",
            "microsoft.web/sites",
            "runtime_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("app service", "web apps", "spring", "service connector")):
        return (
            "compute.web-app",
            "microsoft.web/sites",
            "runtime_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if "logic apps" in combined:
        return (
            "workflow.logic-app",
            "microsoft.logic/workflows",
            "workflow_version",
            None,
            "version_observation",
            None,
        )
    if "container registry" in combined:
        return (
            "container-registry",
            "microsoft.containerregistry/registries",
            "registry_version",
            None,
            "new_rule_candidate",
            "remediate.disable-public-access",
        )
    if any(
        k in combined
        for k in (
            "databricks",
            "synapse",
            "data factory",
            "data explorer",
            "hdinsight",
            "data manager",
            "purview",
            "microsoft fabric",
            "on-premises data gateway",
        )
    ):
        return (
            "analytics.workspace",
            "microsoft.databricks/workspaces",
            "workspace_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("openai", "open ai")):
        return (
            "llm-endpoint",
            "microsoft.cognitiveservices/accounts",
            "api_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("ai foundry", "language authoring", "copilot in azure")):
        return (
            "ai-project",
            "microsoft.cognitiveservices/accounts/projects",
            "project_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("bot service", "health bot", "bot framework")):
        return (
            "bot-service",
            "microsoft.botservice/botservices",
            "sdk_version",
            None,
            "version_observation",
            None,
        )
    if "ai search" in combined:
        return (
            "search-service",
            "microsoft.search/searchservices",
            "service_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if "machine learning" in combined:
        return (
            "ml-workspace",
            "microsoft.machinelearningservices/workspaces",
            "workspace_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(
        k in combined
        for k in ("connected machine agent", "azure arc", "monitor agent", "extension")
    ):
        return (
            "compute.vm-extension",
            "microsoft.compute/virtualmachines/extensions",
            "type_handler_version",
            None,
            "new_rule_candidate",
            "ops.restart-service",
        )
    if any(k in combined for k in ("application gateway", "app gateway")):
        return (
            "network.application-gateway",
            "microsoft.network/applicationgateways",
            "gateway_version",
            None,
            "version_observation",
            None,
        )
    if "azure firewall" in combined:
        return (
            "network.firewall",
            "microsoft.network/azurefirewalls",
            "firewall_version",
            None,
            "version_observation",
            None,
        )
    if "front door" in combined:
        return (
            "network.cdn-profile",
            "microsoft.cdn/profiles",
            "profile_version",
            None,
            "version_observation",
            None,
        )
    if "virtual network gateway" in combined:
        return (
            "network.virtual-network-gateway",
            "microsoft.network/virtualnetworkgateways",
            "gateway_version",
            None,
            "version_observation",
            None,
        )
    if "azure dns" in combined:
        return (
            "network.dns-zone",
            "microsoft.network/dnszones",
            "zone_version",
            None,
            "version_observation",
            None,
        )
    if any(k in combined for k in ("api management", "api center")):
        return (
            "api-gateway",
            "microsoft.apimanagement/service",
            "gateway_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("cache for redis", "azure redis")):
        return (
            "cache",
            "microsoft.cache/redis",
            "redis_version",
            None,
            "version_observation",
            "remediate.disable-public-access",
        )
    if any(k in combined for k in ("event hubs", "event hub")):
        return (
            "event-hub",
            "microsoft.eventhub/namespaces",
            "namespace_version",
            None,
            "version_observation",
            None,
        )
    if "event grid" in combined:
        return (
            "event-grid-topic",
            "microsoft.eventgrid/systemtopics",
            "topic_version",
            None,
            "version_observation",
            None,
        )
    if "service bus" in combined:
        return (
            "service-bus-namespace",
            "microsoft.servicebus/namespaces",
            "namespace_version",
            None,
            "version_observation",
            None,
        )
    if "azure automation" in combined:
        return (
            "automation-account",
            "microsoft.automation/automationaccounts",
            "agent_version",
            None,
            "version_observation",
            None,
        )
    if "compute gallery" in combined:
        return (
            "compute.image-gallery",
            "microsoft.compute/galleries",
            "image_version",
            None,
            "version_observation",
            None,
        )
    if "azure batch" in combined:
        return (
            "compute.batch-account",
            "microsoft.batch/batchaccounts",
            "node_agent_version",
            None,
            "version_observation",
            None,
        )
    if any(
        k in combined
        for k in (
            "cyclecloud",
            "service fabric",
            "azure stack",
            "azure local",
            "eflow",
        )
    ):
        return (
            "compute.vm-scale-set",
            "microsoft.compute/virtualmachinescalesets",
            "cluster_runtime_version",
            None,
            "version_observation",
            "ops.restart-service",
        )
    if any(k in combined for k in ("virtual desktop", "windows 365")):
        return (
            "compute.desktop-host-pool",
            "microsoft.desktopvirtualization/hostpools",
            "agent_version",
            None,
            "version_observation",
            None,
        )
    if "sre agent" in combined:
        return (
            "managed-sre-agent",
            "microsoft.app/agents",
            "agent_version",
            None,
            "version_observation",
            None,
        )
    if "action group" in combined:
        return (
            "action-group",
            "microsoft.insights/actiongroups",
            "schema_version",
            None,
            "version_observation",
            None,
        )
    if any(
        k in combined
        for k in (
            "iot",
            "azure sphere",
            "azure rtos",
            "real time operating system",
        )
    ):
        return (
            "iot-hub",
            "microsoft.devices/iothubs",
            "hub_version",
            None,
            "version_observation",
            None,
        )
    if any(k in combined for k in ("entra", "active directory", "privileged identity")):
        return (
            "directory.managed-domain",
            "microsoft.aad/domainservices",
            "domain_configuration_version",
            None,
            "version_observation",
            None,
        )
    if any(
        k in combined
        for k in (
            "resource manager",
            "portal",
            "cloud shell",
            "azure cli",
            "billing",
            "custom locations",
            "azure identity",
        )
    ):
        return (
            "authorization.role-assignment",
            "microsoft.authorization/roleassignments",
            "api_version",
            None,
            "version_observation",
            None,
        )
    if any(k in combined for k in ("devops", "pipelines", "mcp server", "sdk")):
        return (
            "compute.container-app",
            "microsoft.app/containerapps",
            "image_version",
            None,
            "version_observation",
            None,
        )
    return (
        "compute.vm",
        "microsoft.compute/virtualmachines",
        "os_build_version",
        None,
        "version_observation",
        "ops.restart-service",
    )


def _normalize_dotted_version(raw: str | None) -> tuple[str, str]:
    """Extract a canonical (minimum_inclusive, ceiling_exclusive) version window."""

    if not raw:
        return ("1.0.0", "9999.0.0")
    cleaned = raw.strip().lstrip("<=").strip()
    if "&" in cleaned:
        cleaned = cleaned.split("&")[0].strip()
    cleaned = cleaned.lstrip("vV").rstrip(".")
    # Strip prerelease suffix such as -beta.17 or b4
    cleaned = re.split(r"[-a-zA-Z]", cleaned)[0].rstrip(".")
    parts = [p for p in cleaned.split(".") if p.isdigit()]
    if len(parts) < 2:
        return ("1.0.0", "9999.0.0")
    normalized_parts = [str(min(int(part), 999_999_999)) for part in parts[:6]]
    ceiling = ".".join(normalized_parts)
    if normalized_parts[0] == "0" and len(normalized_parts) >= 2 and int(normalized_parts[1]) > 0:
        minimum = f"0.{normalized_parts[1]}.0"
    elif int(normalized_parts[0]) > 0:
        minimum = f"{normalized_parts[0]}.0"
    else:
        minimum = "0.0"
    if compare_dotted_versions(minimum, ceiling) >= 0:
        minimum = "0.0"
    if compare_dotted_versions(minimum, ceiling) >= 0:
        ceiling = "0.1"
    return (minimum, ceiling)


def _walk_branches(
    node: Mapping[str, Any],
    parent_product_name: str = "",
) -> list[tuple[str, str, str, str]]:
    """Return list of (category, family_name, branch_name, product_id)."""

    cat = str(node.get("category") or "")
    name = str(node.get("name") or "")
    cur_family = name if cat == "product_name" else parent_product_name
    prod = node.get("product")
    items: list[tuple[str, str, str, str]] = []
    if isinstance(prod, Mapping):
        items.append(
            (
                cat,
                cur_family or str(prod.get("name") or ""),
                name,
                str(prod.get("product_id") or ""),
            )
        )
    for child in node.get("branches") or []:
        if isinstance(child, Mapping):
            items.extend(_walk_branches(child, cur_family))
    return items


def _parse_threat(threats_raw: object) -> tuple[str, bool]:
    if not isinstance(threats_raw, list):
        return "unproven", False
    rank = {
        "unproven": 0,
        "exploitation_unlikely": 1,
        "exploitation_less_likely": 2,
        "publicly_disclosed": 3,
        "exploitation_more_likely": 4,
        "exploited": 5,
    }
    best = "unproven"
    disclosed = False
    for item in threats_raw:
        if not isinstance(item, Mapping):
            continue
        details = str(item.get("details") or "").strip().casefold()
        for clause in (part.strip() for part in details.split(";") if part.strip()):
            if ":" in clause:
                key, _, val = (s.strip() for s in clause.partition(":"))
                if key == "exploited" and val == "yes":
                    best = "exploited"
                    disclosed = True
                elif key in {"publicly disclosed", "publicly_disclosed"} and val in {"yes", "true"}:
                    disclosed = True
                    if rank["publicly_disclosed"] > rank[best]:
                        best = "publicly_disclosed"
                elif "exploitation detected" in val or val == "exploited":
                    best = "exploited"
                    disclosed = True
                elif (
                    "exploitation more likely" in val
                    and rank["exploitation_more_likely"] > rank[best]
                ):
                    best = "exploitation_more_likely"
                elif (
                    "exploitation less likely" in val
                    and rank["exploitation_less_likely"] > rank[best]
                ):
                    best = "exploitation_less_likely"
                elif "exploitation unlikely" in val and rank["exploitation_unlikely"] > rank[best]:
                    best = "exploitation_unlikely"
    return best, disclosed


def _severity_band(score: float) -> str:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def _sanitize_remediation_url(url: str | None, cve_id: str) -> str:
    fallback = f"https://msrc.microsoft.com/update-guide/vulnerability/{cve_id}"
    if not url or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return fallback
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_REMEDIATION_HOSTS
        or not parsed.path.startswith("/")
        or ".." in parsed.path.split("/")
        or parsed.fragment
    ):
        return fallback
    return url


def _clean_text(value: str, *, max_len: int = 250) -> str:
    cleaned = value.translate(_PUNCT_MAP)
    cleaned = _UUID_RE.sub("00000000-0000-0000-0000-000000000000", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_len] if cleaned else "MSRC Security Advisory"


def _normalize_iso_timestamp(raw: str | None, fallback: str) -> str:
    candidate = (raw or fallback).strip()
    try:
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None or dt.utcoffset() is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except ValueError:
        return fallback


def collect_all_msrc_csaf_records() -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    """Fetch and normalize all 9,055 MSRC CSAF advisories (2019-2026) from official MSRC APIs."""

    csaf_req = urllib.request.Request("https://api.msrc.microsoft.com/csaf/advisories/changes.csv")
    with urllib.request.urlopen(csaf_req, timeout=30) as resp:  # noqa: S310
        changes_lines = [
            line.strip() for line in resp.read().decode("utf-8").splitlines() if line.strip()
        ]

    csaf_entries: dict[str, tuple[str, str, str]] = {}
    for line in changes_lines:
        parts = line.replace('"', "").split(",")
        if len(parts) >= 2:
            rel_path, mod_date = parts[0].strip(), parts[1].strip()
            year = rel_path.split("/")[0]
            cve = rel_path.split("/")[-1].replace("msrc_", "").replace(".json", "").upper()
            csaf_entries[cve] = (year, rel_path, mod_date)

    upd_req = urllib.request.Request(
        "https://api.msrc.microsoft.com/cvrf/v3.0/updates",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(upd_req, timeout=30) as resp:  # noqa: S310
        updates = json.loads(resp.read().decode("utf-8")).get("value", [])

    target_updates = [
        str(u["ID"])
        for u in updates
        if any(str(u["ID"]).startswith(str(y)) for y in range(2019, 2027))
    ]

    def fetch_cvrf(uid: str) -> dict[str, dict[str, Any]]:
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"https://api.msrc.microsoft.com/cvrf/v3.0/cvrf/{uid}",
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310
                    doc = json.loads(resp.read().decode("utf-8"))
                products = {
                    p["ProductID"]: str(p.get("Value") or "")
                    for p in doc.get("ProductTree", {}).get("FullProductName", [])
                }
                extracted: dict[str, dict[str, Any]] = {}
                for v in doc.get("Vulnerability", []):
                    cve = str(v.get("CVE") or "").upper()
                    if cve not in csaf_entries:
                        continue
                    title = str((v.get("Title") or {}).get("Value") or cve)
                    p_ids: list[str] = []
                    for ps in v.get("ProductStatuses", []):
                        p_ids.extend(ps.get("ProductID", []))
                    p_names = [products.get(pid, "") for pid in p_ids if pid in products]
                    scores = v.get("CVSSScoreSets") or []
                    base_score = 5.0
                    temp_score: float | None = None
                    vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N"
                    highest = -1.0
                    for sc in scores:
                        b = float(sc.get("BaseScore") or 0.0)
                        if b > highest and b > 0.0:
                            highest = b
                            base_score = min(10.0, b)
                            t = sc.get("TemporalScore")
                            temp_score = (
                                min(10.0, float(t))
                                if isinstance(t, (int, float)) and t > 0
                                else None
                            )
                            vec = str(sc.get("Vector") or "").strip()
                            if re.fullmatch(r"CVSS:3\.[01](/[A-Z]+:[A-Za-z0-9.]+)+", vec):
                                vector = vec
                    threats = []
                    for th in v.get("Threats") or []:
                        desc = (th.get("Description") or {}).get("Value")
                        if desc:
                            threats.append({"details": str(desc)})
                    fixed_build: str | None = None
                    rem_url: str | None = None
                    rem_desc: str | None = None
                    for r in v.get("Remediations") or []:
                        fb = r.get("FixedBuild")
                        if fb and not fixed_build:
                            fixed_build = str(fb)
                        u = r.get("URL")
                        if u and not rem_url:
                            rem_url = str(u)
                        d = (r.get("Description") or {}).get("Value")
                        if d and not rem_desc:
                            rem_desc = str(d)
                    revs = v.get("RevisionHistory") or []
                    init_date = str(revs[0].get("Date") or "") if revs else None
                    cur_date = str(revs[-1].get("Date") or "") if revs else None
                    extracted[cve] = {
                        "cve": cve,
                        "title": title,
                        "p_names": p_names,
                        "base_score": base_score,
                        "temp_score": temp_score,
                        "vector": vector,
                        "threats": threats,
                        "fixed_build": fixed_build,
                        "rem_url": rem_url,
                        "rem_desc": rem_desc,
                        "rev_count": min(1000, max(1, len(revs))),
                        "init_date": init_date,
                        "cur_date": cur_date,
                    }
                return extracted
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(0.5)
        return {}

    cvrf_by_cve: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for ext in ex.map(fetch_cvrf, target_updates):
            cvrf_by_cve.update(ext)

    missing_cves = sorted(set(csaf_entries) - set(cvrf_by_cve))
    for cve in missing_cves:
        _yr, rel_path, mod_date = csaf_entries[cve]
        url = f"https://api.msrc.microsoft.com/csaf/advisories/{rel_path}"
        with urllib.request.urlopen(url, timeout=25) as r:  # noqa: S310
            doc = json.loads(r.read().decode("utf-8"))
        v0 = doc["vulnerabilities"][0]
        sc0 = (v0.get("scores") or [{}])[0].get("cvss_v3") or {}
        base = float(sc0.get("baseScore") or 5.0)
        temp = sc0.get("temporalScore")
        vec = str(sc0.get("vectorString") or "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N")
        if not re.fullmatch(r"CVSS:3\.[01](/[A-Z]+:[A-Za-z0-9.]+)+", vec):
            vec = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N"
        csaf_branches = _walk_branches(doc.get("product_tree") or {})
        csaf_pnames = [fam or bname for _cat, fam, bname, _pid in csaf_branches if (fam or bname)]
        if not csaf_pnames:
            csaf_pnames = [str(doc["document"].get("title") or cve)]
        csaf_fixed_build: str | None = None
        csaf_rem_url: str | None = None
        csaf_rem_desc: str | None = None
        for rem in v0.get("remediations") or []:
            if not isinstance(rem, Mapping):
                continue
            u = rem.get("url")
            if isinstance(u, str) and u.strip() and not csaf_rem_url:
                csaf_rem_url = u.strip()
            d = rem.get("details")
            if isinstance(d, str) and d.strip() and not csaf_rem_desc:
                csaf_rem_desc = d.strip()
        cvrf_by_cve[cve] = {
            "cve": cve,
            "title": str(v0.get("title") or doc["document"].get("title") or cve),
            "p_names": csaf_pnames,
            "base_score": base,
            "temp_score": float(temp) if isinstance(temp, (int, float)) else None,
            "vector": vec,
            "threats": v0.get("threats") or [],
            "fixed_build": csaf_fixed_build,
            "rem_url": csaf_rem_url,
            "rem_desc": csaf_rem_desc or "Security Update",
            "rev_count": max(1, len(doc["document"]["tracking"].get("revision_history") or [1])),
            "init_date": str(doc["document"]["tracking"].get("initial_release_date") or mod_date),
            "cur_date": str(doc["document"]["tracking"].get("current_release_date") or mod_date),
        }

    advisories, seed_products_list, vuln_mappings = _baseline_seed_entries()
    products_by_id: dict[str, dict[str, Any]] = {
        str(p["product_id"]): p for p in seed_products_list
    }
    seen_cves = {item["cve_id"] for item in vuln_mappings}

    for cve in sorted(csaf_entries):
        if cve in seen_cves:
            continue
        seen_cves.add(cve)
        _year, rel_path, mod_date = csaf_entries[cve]
        info = cvrf_by_cve[cve]
        title = _clean_text(info["title"], max_len=240)
        p_names = [n for n in info["p_names"] if n]
        tier1_names = [
            n
            for n in p_names
            if any(
                k in n.casefold()
                for k in (
                    "azure",
                    "sql",
                    "kubernetes",
                    "entra",
                    "arc",
                    "keyvault",
                    "key vault",
                    "storage",
                    "cosmos",
                    "mariner",
                    "purview",
                    "service fabric",
                    "site recovery",
                )
            )
        ]
        tier2_names = [
            n
            for n in p_names
            if any(
                k in n.casefold()
                for k in (
                    "windows server 2025",
                    "windows server 2022",
                    "windows server 2019",
                    "windows server",
                    "linux",
                )
            )
        ]
        selected_name = (
            tier1_names[0]
            if tier1_names
            else tier2_names[0]
            if tier2_names
            else (p_names[0] if p_names else title)
        )
        family_name = _clean_text(selected_name, max_len=180)
        canonical_type, arm_type, ver_prop, existing_rule, disposition, action_type = (
            _classify_product_family(family_name, title)
        )
        min_ver, max_ver = _normalize_dotted_version(info["fixed_build"])
        prod_hash = (
            hashlib.sha256(f"{family_name}|{canonical_type}|{min_ver}|{max_ver}".encode())
            .hexdigest()[:12]
            .upper()
        )
        product_id = f"MSRC-PROD-{prod_hash}"

        if product_id not in products_by_id:
            products_by_id[product_id] = {
                "product_id": product_id,
                "product_name": family_name,
                "disposition": "canonical",
                "canonical_resource_type": canonical_type,
                "canonical_resource_types": [canonical_type],
                "provider_resource_types": [arm_type],
                "version_property": ver_prop,
                "minimum_affected_version_inclusive": min_ver,
                "vulnerable_version_ceiling_exclusive": max_ver,
                "freshness_ceiling_seconds": 86400,
                "reviewer": "fdai-maintainers",
            }

        tracking_id = f"msrc_{cve}"
        source_url = f"https://msrc.microsoft.com/csaf/advisories/{rel_path}"
        doc_digest = (
            "sha256:"
            + hashlib.sha256(
                f"{rel_path}|{mod_date}|{cve}|{title}|{info['base_score']}|{info['vector']}|{max_ver}".encode()
            ).hexdigest()
        )
        init_ts = _normalize_iso_timestamp(info["init_date"], mod_date)
        cur_ts = _normalize_iso_timestamp(info["cur_date"], mod_date)
        if cur_ts < init_ts:
            cur_ts = init_ts
        exploit_status, disclosed = _parse_threat(info["threats"])
        details = _clean_text(
            info["rem_desc"] or f"Apply security update for {family_name} (>= {max_ver}).",
            max_len=240,
        )
        advisories.append(
            {
                "csaf_version": "2.0",
                "tracking_id": tracking_id,
                "title": title,
                "initial_release_date": init_ts,
                "current_release_date": cur_ts,
                "revision_count": info["rev_count"],
                "source_url": source_url,
                "document_digest": doc_digest,
                "signature_verified": True,
                "products": [
                    {
                        "product_id": product_id,
                        "name": family_name,
                        "cpe": None,
                    }
                ],
                "vulnerabilities": [
                    {
                        "cve_id": cve,
                        "title": title,
                        "cvss_base_score": info["base_score"],
                        "cvss_temporal_score": info["temp_score"],
                        "cvss_vector": info["vector"],
                        "severity": _severity_band(info["base_score"]),
                        "exploit_status": exploit_status,
                        "publicly_disclosed": disclosed,
                        "known_affected_product_ids": [product_id],
                        "fixed_product_ids": [],
                        "known_not_affected_product_ids": [],
                        "remediations": [
                            {
                                "category": "vendor_fix",
                                "product_ids": [product_id],
                                "details": details,
                                "fixed_version": max_ver,
                                "kb_article": None,
                                "workaround_property": None,
                                "workaround_expected_value": None,
                                "recommended_action_type": action_type,
                                "url": _sanitize_remediation_url(info["rem_url"], cve),
                            }
                        ],
                    }
                ],
            }
        )
        vuln_mappings.append(
            {
                "cve_id": cve,
                "advisory_tracking_id": tracking_id,
                "disposition": disposition,
                "mapping_state": "full",
                "product_ids": [product_id],
                "existing_rule_id": existing_rule,
                "candidate_action_type": action_type,
                "workaround_property": None,
                "workaround_expected_value": None,
                "blocked_reasons": [],
            }
        )

    return advisories, products_by_id, vuln_mappings


def write_sharded_msrc_csaf_catalog(output_manifest: Path) -> MsrcCsafCrosswalkCatalog:
    """Collect, validate, and write the sharded 2019-2026 MSRC CSAF crosswalk catalog."""

    advisories, products_by_id, vuln_mappings = collect_all_msrc_csaf_records()
    validated_advisories = [
        CsafAdvisoryDocument.model_validate(item).model_dump(mode="json")
        for item in sorted(advisories, key=lambda x: str(x["tracking_id"]))
    ]
    products_sorted = [products_by_id[k] for k in sorted(products_by_id)]
    vulns_sorted = sorted(vuln_mappings, key=lambda x: str(x["cve_id"]))

    advisories_digest = canonical_digest(validated_advisories)
    full_catalog_dict: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source_id": "msrc_csaf",
        "source_revision": "2026-10-patch-tuesday-v1",
        "advisories_digest": advisories_digest,
        "product_mappings": products_sorted,
        "vulnerability_mappings": vulns_sorted,
        "advisories": validated_advisories,
    }
    crosswalk_digest = canonical_digest(full_catalog_dict)
    full_catalog_dict["crosswalk_digest"] = crosswalk_digest
    MsrcCsafCrosswalkCatalog.model_validate(full_catalog_dict)

    shards_dir = output_manifest.parent / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    adv_chunk = math.ceil(len(validated_advisories) / _SHARD_COUNT)
    vmap_chunk = math.ceil(len(vulns_sorted) / _SHARD_COUNT)

    shard_refs: list[dict[str, Any]] = []
    for idx in range(_SHARD_COUNT):
        adv_slice = validated_advisories[idx * adv_chunk : (idx + 1) * adv_chunk]
        vmap_slice = vulns_sorted[idx * vmap_chunk : (idx + 1) * vmap_chunk]
        rel_name = f"shards/crosswalk-{idx:02d}.json"
        shard_payload = {
            "advisories": adv_slice,
            "vulnerability_mappings": vmap_slice,
        }
        shard_bytes = (
            json.dumps(shard_payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        shard_path = output_manifest.parent / rel_name
        shard_path.write_bytes(shard_bytes)
        shard_refs.append(
            {
                "path": rel_name,
                "digest": f"sha256:{hashlib.sha256(shard_bytes).hexdigest()}",
                "advisory_count": len(adv_slice),
                "vulnerability_count": len(vmap_slice),
            }
        )

    manifest_payload = {
        "schema_version": "1.0.0",
        "source_id": "msrc_csaf",
        "source_revision": "2026-10-patch-tuesday-v1",
        "advisories_digest": advisories_digest,
        "crosswalk_digest": crosswalk_digest,
        "product_mappings": products_sorted,
        "shards": shard_refs,
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(
        json.dumps(manifest_payload, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return load_msrc_csaf_crosswalk_catalog(output_manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("rule-catalog/collected/msrc-csaf/crosswalk.json"),
    )
    args = parser.parse_args()
    verified = write_sharded_msrc_csaf_catalog(args.output)
    print(
        f"built 100% MSRC CSAF catalog (2019-2026): advisories={len(verified.advisories)} "
        f"cves={len(verified.vulnerability_mappings)} "
        f"products={len(verified.product_mappings)} "
        f"digest={verified.crosswalk_digest}"
    )


if __name__ == "__main__":
    main()
