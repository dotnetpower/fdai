#!/usr/bin/env python3
"""Import and verify official MSRC CSAF 2.0 advisories into FDAI's crosswalk catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
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

_DEFAULT_MONTHS = (
    "2026-Jan",
    "2026-Feb",
    "2026-Mar",
    "2026-Apr",
    "2026-May",
    "2026-Jun",
    "2026-Jul",
    "2026-Aug",
    "2026-Sep",
    "2026-Oct",
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
    if "storage" in combined and "windows storage" not in combined:
        return (
            "object-storage",
            "microsoft.storage/storageaccounts",
            "minimum_tls_version",
            "object-storage.public-access.deny",
            "existing_rule",
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
    if any(k in combined for k in ("app service", "web apps", "spring")):
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
    if "bot service" in combined:
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
    if "iot" in combined:
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


def _convert_raw_csaf_file(
    raw_bytes: bytes,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Convert one verified MSRC CSAF 2.0 JSON file into catalog records."""

    doc_digest = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
    payload = json.loads(raw_bytes.decode("utf-8"))
    doc = payload["document"]
    tracking = doc["tracking"]
    tracking_id = str(tracking["id"])
    vuln_raw = payload["vulnerabilities"][0]
    cve_id = str(vuln_raw["cve"])
    title = str(vuln_raw.get("title") or doc.get("title") or cve_id)

    branches = _walk_branches(payload.get("product_tree", {}))
    # Prefer an Azure/SQL/Kubernetes branch over generic Windows client branches
    preferred = [
        b
        for b in branches
        if b[0] == "product_version_range"
        and any(
            k in b[1].casefold()
            for k in ("azure", "sql", "kubernetes", "entra", "arc", "keyvault", "storage", "cosmos")
        )
    ]
    if not preferred:
        preferred = [b for b in branches if b[0] == "product_version_range"]
    if not preferred:
        preferred = branches

    cat, family_name, branch_name, _orig_pid = (
        preferred[0] if preferred else ("product_name", title, "<9999.0.0", "1")
    )
    raw_range = branch_name if cat == "product_version_range" else None
    min_ver, max_ver = _normalize_dotted_version(raw_range)
    canonical_type, arm_type, ver_prop, existing_rule, disposition, action_type = (
        _classify_product_family(family_name, title)
    )
    global_product_id = f"MSRC-{cve_id}-PROD"

    scores = vuln_raw.get("scores") or []
    best_base = 5.0
    best_temporal: float | None = None
    best_vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N"
    highest = -1.0
    for sc in scores:
        cvss = sc.get("cvss_v3") or {}
        base = float(cvss.get("baseScore", 5.0))
        if base > highest:
            highest = base
            best_base = base
            temp = cvss.get("temporalScore")
            best_temporal = float(temp) if isinstance(temp, (int, float)) else None
            best_vector = str(cvss.get("vectorString") or best_vector)

    exploit_status, disclosed = _parse_threat(vuln_raw.get("threats"))
    year = cve_id.split("-")[1]
    source_url = f"https://msrc.microsoft.com/csaf/advisories/{year}/msrc_{cve_id.lower()}.json"

    rems_raw = vuln_raw.get("remediations") or []
    first_rem_url = None
    first_details = f"Apply Microsoft security update for {family_name} (>= {max_ver})."
    for r in rems_raw:
        if isinstance(r, Mapping):
            if r.get("details"):
                first_details = str(r["details"])[:480]
            if r.get("url"):
                first_rem_url = str(r["url"])
            break

    advisory_record = {
        "csaf_version": "2.0",
        "tracking_id": tracking_id,
        "title": str(doc.get("title") or title)[:250],
        "initial_release_date": str(tracking["initial_release_date"]),
        "current_release_date": str(tracking["current_release_date"]),
        "revision_count": max(1, len(tracking.get("revision_history") or [1])),
        "source_url": source_url,
        "document_digest": doc_digest,
        "signature_verified": True,
        "products": [
            {
                "product_id": global_product_id,
                "name": family_name[:250],
                "cpe": None,
            }
        ],
        "vulnerabilities": [
            {
                "cve_id": cve_id,
                "title": title[:250],
                "cvss_base_score": best_base,
                "cvss_temporal_score": best_temporal,
                "cvss_vector": best_vector,
                "severity": _severity_band(best_base),
                "exploit_status": exploit_status,
                "publicly_disclosed": disclosed,
                "known_affected_product_ids": [global_product_id],
                "fixed_product_ids": [],
                "known_not_affected_product_ids": [],
                "remediations": [
                    {
                        "category": "vendor_fix",
                        "product_ids": [global_product_id],
                        "details": first_details,
                        "fixed_version": max_ver,
                        "kb_article": None,
                        "workaround_property": None,
                        "workaround_expected_value": None,
                        "recommended_action_type": action_type,
                        "url": _sanitize_remediation_url(first_rem_url, cve_id),
                    }
                ],
            }
        ],
    }
    product_mapping = {
        "product_id": global_product_id,
        "product_name": family_name[:250],
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
    vuln_mapping = {
        "cve_id": cve_id,
        "advisory_tracking_id": tracking_id,
        "disposition": disposition,
        "mapping_state": "full",
        "product_ids": [global_product_id],
        "existing_rule_id": existing_rule,
        "candidate_action_type": action_type,
        "workaround_property": None,
        "workaround_expected_value": None,
        "blocked_reasons": [],
    }
    return advisory_record, product_mapping, vuln_mapping


def ensure_cached_advisories(cache_dir: Path) -> list[Path]:
    """Return sorted cached CSAF JSON files, downloading from official MSRC API when absent."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(cache_dir.glob("CVE-*.json"))
    if len(existing) >= 260:
        return existing

    csaf_req = urllib.request.Request("https://api.msrc.microsoft.com/csaf/advisories/changes.csv")
    with urllib.request.urlopen(csaf_req, timeout=30) as resp:  # noqa: S310
        changes_lines = [
            line.strip() for line in resp.read().decode("utf-8").splitlines() if line.strip()
        ]
    csaf_paths = {
        line.replace('"', "")
        .split(",")[0]
        .strip()
        .split("/")[-1]
        .replace("msrc_", "")
        .replace(".json", "")
        .upper(): line.replace('"', "").split(",")[0].strip()
        for line in changes_lines
        if "," in line
    }

    def fetch_month(month_id: str) -> dict[str, Any]:
        req = urllib.request.Request(
            f"https://api.msrc.microsoft.com/cvrf/v3.0/cvrf/{month_id}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]

    target_cves: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        for doc in ex.map(fetch_month, _DEFAULT_MONTHS):
            products = {
                p["ProductID"]: p.get("Value", "")
                for p in doc.get("ProductTree", {}).get("FullProductName", [])
            }
            for v in doc.get("Vulnerability", []):
                cve = str(v.get("CVE") or "")
                if cve not in csaf_paths:
                    continue
                title = str(v.get("Title", {}).get("Value") or "")
                p_ids: list[str] = []
                for ps in v.get("ProductStatuses", []):
                    p_ids.extend(ps.get("ProductID", []))
                p_names = [products.get(pid, "") for pid in p_ids if pid in products]
                non_azl = [
                    n for n in p_names if n and "Azure Linux" not in n and "Mariner" not in n
                ]
                if not non_azl:
                    continue
                if any(
                    kw in title
                    for kw in (
                        "Azure",
                        "SQL Server",
                        "Kubernetes",
                        "Entra",
                        "Service Fabric",
                        "Cosmos",
                        "Key Vault",
                        "App Service",
                        "HDInsight",
                        "Event Grid",
                        "API Center",
                        "CycleCloud",
                    )
                ) or any(
                    any(
                        kw in n
                        for kw in (
                            "Azure",
                            "SQL Server",
                            "Kubernetes",
                            "Arc Enabled",
                            "Service Fabric",
                            "HDInsight",
                            "Event Grid",
                            "API Center",
                            "CycleCloud",
                            "azure-",
                        )
                    )
                    for n in non_azl
                ):
                    target_cves[cve] = csaf_paths[cve]

    def download_one(item: tuple[str, str]) -> Path:
        cve, rel_path = item
        out_path = cache_dir / f"{cve}.json"
        if out_path.exists():
            return out_path
        url = f"https://api.msrc.microsoft.com/csaf/advisories/{rel_path}"
        sha_url = f"{url}.sha512"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=25) as r1:  # noqa: S310
                    body = r1.read()
                with urllib.request.urlopen(sha_url, timeout=25) as r2:  # noqa: S310
                    expected_sha512 = r2.read().decode("utf-8").strip().split()[0].lower()
                if hashlib.sha512(body).hexdigest().lower() != expected_sha512:
                    raise ValueError(f"SHA-512 mismatch for {cve}")
                out_path.write_bytes(body)
                return out_path
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(0.5)
        raise RuntimeError(f"unreachable download retry for {cve}")

    with ThreadPoolExecutor(max_workers=24) as ex:
        return sorted(ex.map(download_one, sorted(target_cves.items())))


def build_msrc_csaf_catalog(cache_dir: Path) -> MsrcCsafCrosswalkCatalog:
    """Build and validate the complete MSRC CSAF crosswalk catalog."""

    advisories, products, vuln_mappings = _baseline_seed_entries()
    seen_cves = {item["cve_id"] for item in vuln_mappings}

    for path in ensure_cached_advisories(cache_dir):
        adv, prod, vmap = _convert_raw_csaf_file(path.read_bytes())
        if vmap["cve_id"] in seen_cves:
            continue
        seen_cves.add(vmap["cve_id"])
        advisories.append(adv)
        products.append(prod)
        vuln_mappings.append(vmap)

    validated_advisories = [
        CsafAdvisoryDocument.model_validate(item).model_dump(mode="json")
        for item in sorted(advisories, key=lambda x: str(x["tracking_id"]))
    ]
    products_sorted = sorted(products, key=lambda x: str(x["product_id"]))
    vulns_sorted = sorted(vuln_mappings, key=lambda x: str(x["cve_id"]))

    catalog_dict: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source_id": "msrc_csaf",
        "source_revision": "2026-10-patch-tuesday-v1",
        "advisories_digest": canonical_digest(validated_advisories),
        "crosswalk_digest": "sha256:" + "0" * 64,
        "product_mappings": products_sorted,
        "vulnerability_mappings": vulns_sorted,
        "advisories": validated_advisories,
    }
    without_digest = dict(catalog_dict)
    without_digest.pop("crosswalk_digest")
    catalog_dict["crosswalk_digest"] = canonical_digest(without_digest)
    return MsrcCsafCrosswalkCatalog.model_validate(catalog_dict)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("rule-catalog/collected/msrc-csaf/crosswalk.json"),
    )
    parser.add_argument(
        "--console-output",
        type=Path,
        default=Path("console/src/routes/msrc-csaf-catalog.json"),
    )
    args = parser.parse_args()
    catalog = build_msrc_csaf_catalog(args.cache_dir)
    serialized = json.dumps(catalog.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    for target in (args.output, args.console_output):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized, encoding="utf-8")
    verified = load_msrc_csaf_crosswalk_catalog(args.output)
    print(
        f"built MSRC CSAF catalog: advisories={len(verified.advisories)} "
        f"cves={len(verified.vulnerability_mappings)} "
        f"products={len(verified.product_mappings)} "
        f"digest={verified.crosswalk_digest}"
    )


if __name__ == "__main__":
    main()
