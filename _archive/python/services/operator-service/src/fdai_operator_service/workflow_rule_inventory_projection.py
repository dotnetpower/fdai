"""Resolve active inventory resources and baseline outcomes for all catalog Rules."""

# ruff: noqa: S608 - SQL clauses are module-owned; request values remain bound parameters.

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from datetime import datetime
from typing import Any

from fdai_operator_service.workflow_rule_projection import (
    BASELINE_EVALUATION_LATEST_COVERAGE_KEY,
    BASELINE_EVALUATION_OUTCOME_PREFIX,
)

_MAX_RELATED_RESOURCES = 50
_MAX_SAMPLE_NAMES = 5
_RG_PATTERN = re.compile(r"/resource-group/([^/]+)|/resourceGroups/([^/]+)", re.IGNORECASE)

_EFFECTIVE_RESOURCES_CTE = (
    "WITH active_snap AS ("
    "SELECT snapshot.id AS snapshot_id "
    "FROM inventory_active AS active "
    "JOIN inventory_snapshot AS snapshot ON snapshot.id = active.snapshot_id "
    "WHERE active.singleton = TRUE "
    "AND snapshot.status = 'active' "
    "AND snapshot.completed_at IS NOT NULL "
    "LIMIT 1), "
    "effective_resources AS ("
    "SELECT snapshot.resource_id, snapshot.resource_type, "
    "CASE WHEN overlay.resource_id IS NULL THEN snapshot.props "
    "ELSE snapshot.props || overlay.props END AS props, "
    "COALESCE(overlay.observed_at, snapshot.last_seen) AS last_seen "
    "FROM inventory_snapshot_resource snapshot "
    "JOIN active_snap ON snapshot.snapshot_id = active_snap.snapshot_id "
    "LEFT JOIN inventory_realtime_resource overlay "
    "ON overlay.resource_id = snapshot.resource_id AND overlay.change_kind = 'upsert' "
    "WHERE NOT EXISTS (SELECT 1 FROM inventory_realtime_resource removed "
    "WHERE removed.resource_id = snapshot.resource_id AND removed.change_kind = 'delete') "
    "UNION ALL "
    "SELECT overlay.resource_id, overlay.resource_type, overlay.props, overlay.observed_at "
    "FROM inventory_realtime_resource overlay "
    "JOIN active_snap ON TRUE "
    "WHERE overlay.change_kind = 'upsert' "
    "AND NOT EXISTS (SELECT 1 FROM inventory_snapshot_resource snapshot "
    "WHERE snapshot.snapshot_id = active_snap.snapshot_id "
    "AND snapshot.resource_id = overlay.resource_id)) "
)

_EXACT_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "kubernetes-cluster.control-plane": ("kubernetes-cluster", "kubernetes-node-pool"),
    "kubernetes-cluster.policies": ("kubernetes-cluster", "kubernetes-node-pool"),
    "kubernetes-cluster.managed": ("kubernetes-cluster", "kubernetes-node-pool"),
    "kubernetes-cluster.etcd": ("kubernetes-cluster", "kubernetes-node-pool"),
    "kubernetes-cluster": ("kubernetes-cluster", "kubernetes-node-pool"),
    "kubernetes-node-pool": ("kubernetes-node-pool", "kubernetes-cluster"),
    "web.app-service": (
        "compute.container-app",
        "static-web-app",
        "compute.function",
        "app-service-plan",
    ),
    "microsoft.web.sites": (
        "compute.container-app",
        "static-web-app",
        "compute.function",
        "app-service-plan",
    ),
    "postgresql-flexible": ("postgresql-server",),
    "sql-server": ("postgresql-server",),
    "sql-database": ("postgresql-server",),
    "sql-managed-instance": ("postgresql-server",),
    "cosmos-db": ("postgresql-server", "object-storage"),
    "mysql-server": ("postgresql-server",),
    "cache": ("postgresql-server", "compute.container-app"),
    "network.application-gateway": ("api-gateway", "network.load-balancer"),
}

_PREFIX_TYPE_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        (
            "azure.containerservice",
            "azure.kubernetes",
            "azure.redhatopenshift",
            "kubernetes-cluster",
        ),
        ("kubernetes-cluster", "kubernetes-node-pool"),
    ),
    (
        (
            "azure.web.",
            "microsoft.web.",
            "azure.app.containerapps",
            "azure.app.managedenvironments",
            "azure.appplatform",
        ),
        (
            "compute.container-app",
            "compute.container-app-environment",
            "static-web-app",
            "compute.function",
            "app-service-plan",
        ),
    ),
    (
        (
            "azure.sql",
            "azure.dbforpostgresql",
            "azure.dbformysql",
            "azure.dbformariadb",
            "azure.documentdb",
            "azure.cache",
            "azure.kusto",
            "azure.synapse",
            "azure.databricks",
            "azure.hdinsight",
            "azure.purview",
            "azure.analysisservices",
        ),
        ("postgresql-server", "object-storage"),
    ),
    (
        (
            "azure.keyvault",
            "azure.managedhsm",
            "azure.appconfiguration",
            "azure.attestation",
            "azure.dataprotection",
            "azure.recoveryservices",
        ),
        ("secret-store", "managed-certificate", "managed-identity"),
    ),
    (
        (
            "azure.cognitiveservices",
            "azure.machinelearningservices",
            "azure.search",
            "azure.botservice",
            "azure.healthcareapis",
            "azure.maps",
        ),
        ("llm-endpoint", "llm-model-deployment", "ai-project"),
    ),
    (
        (
            "azure.eventhub",
            "azure.servicebus",
            "azure.eventgrid",
            "azure.signalrservice",
            "azure.relay",
            "azure.notificationhubs",
            "azure.iotcentral",
            "azure.devices",
            "azure.deviceupdate",
            "azure.digitaltwins",
            "azure.streamanalytics",
        ),
        ("event-hub", "event-grid-topic", "communication-service"),
    ),
    (
        (
            "azure.apimanagement",
            "azure.network.applicationgateways",
            "azure.network.frontdoor",
            "azure.cdn",
        ),
        ("api-gateway", "network.load-balancer", "network.public-ip"),
    ),
    (
        (
            "azure.network.firewall",
            "azure.network.azurefirewalls",
            "azure.network.ddosprotectionplans",
            "azure.network.networksecuritygroups",
        ),
        ("network.firewall", "network.firewall-policy", "network.nsg"),
    ),
    (
        ("azure.network.virtualnetworks.subnets",),
        ("network.subnet", "network.vnet"),
    ),
    (
        (
            "azure.network.virtualnetworks",
            "azure.network.virtualwans",
            "azure.network.virtualhubs",
            "azure.network.expressroute",
            "azure.network.vpn",
            "azure.network.connections",
            "azure.network.localnetworkgateways",
            "azure.network.virtualnetworkgateways",
        ),
        ("network.vnet", "network.subnet", "network.route-table"),
    ),
    (
        ("azure.network.networkinterfaces",),
        ("network.interface",),
    ),
    (
        (
            "azure.network.publicip",
            "azure.network.natgateways",
        ),
        ("network.public-ip", "network.nat-gateway"),
    ),
    (
        (
            "azure.network.privateendpoints",
            "azure.network.privatelink",
            "azure.network.privatednszones",
            "azure.hybridcompute.privatelinkscopes",
            "azure.insights.privatelinkscopes",
        ),
        ("network.private-endpoint", "network.private-dns-zone"),
    ),
    (
        (
            "azure.network.dnszones",
            "azure.network.trafficmanager",
            "azure.network.dnsresolver",
        ),
        ("network.dns-zone", "network.registered-domain"),
    ),
    (
        ("azure.network.bastionhosts",),
        ("network.bastion-host",),
    ),
    (
        ("azure.network.loadbalancers",),
        ("network.load-balancer",),
    ),
    (
        ("azure.network.networkwatchers",),
        ("observability.network-monitor",),
    ),
    (
        ("azure.network.",),
        ("network.nsg", "network.vnet", "network.private-endpoint"),
    ),
    (
        (
            "azure.compute.virtualmachines.extensions",
            "azure.hybridcompute.machines.extensions",
        ),
        ("compute.vm-extension", "compute.vm"),
    ),
    (
        (
            "azure.compute.virtualmachinescalesets",
            "azure.batch",
            "azure.servicefabric",
        ),
        ("compute.vm-scale-set", "compute.vm"),
    ),
    (
        ("azure.compute.disks", "azure.compute.snapshots"),
        ("disk",),
    ),
    (
        ("azure.compute.galleries", "azure.compute.images"),
        ("compute.image-gallery", "compute.gallery-image", "compute.image"),
    ),
    (
        (
            "azure.compute.",
            "azure.hybridcompute",
            "azure.sqlvirtualmachine",
            "azure.desktopvirtualization",
            "azure.labservices",
            "azure.azurestackhci",
            "azure.containerinstance",
        ),
        ("compute.vm", "compute.vm-scale-set", "compute.container-app-job"),
    ),
    (
        ("azure.containerregistry",),
        ("container-registry",),
    ),
    (
        (
            "azure.storage",
            "azure.datalakestore",
            "azure.datalakeanalytics",
            "azure.netapp",
            "azure.storagecache",
            "azure.storagesync",
            "azure.elasticsan",
            "azure.databox",
        ),
        ("object-storage", "disk"),
    ),
    (
        (
            "azure.insights",
            "azure.operationalinsights",
            "azure.monitor",
            "azure.alertsmanagement",
            "azure.dashboard",
            "azure.loadtestservice",
            "azure.chaos",
        ),
        (
            "log-workspace",
            "application-insights",
            "anomaly-alert-rule",
            "data-collection-rule",
            "action-group",
        ),
    ),
    (
        (
            "azure.logic",
            "azure.automation",
            "azure.datafactory",
            "azure.powerbi",
            "azure.fabric",
        ),
        ("workflow.logic-app", "compute.container-app-job", "action-group"),
    ),
    (
        (
            "azure.authorization",
            "azure.managedidentity",
            "azure.aad",
            "azure.activedirectory",
            "azure.security",
            "azure.policyinsights",
            "azure.guestconfiguration",
            "azure.automanage",
            "azure.blueprint",
        ),
        ("authorization.role-assignment", "managed-identity", "resource-group"),
    ),
)

_KEYWORD_FALLBACKS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("network", "nsg", "subnet", "vnet", "firewall", "private-endpoint", "public-ip", "tls"),
        ("network.nsg", "network.vnet", "network.private-endpoint", "network.public-ip"),
    ),
    (
        ("storage", "blob", "file", "disk", "backup"),
        ("object-storage", "disk"),
    ),
    (
        ("keyvault", "secret", "key", "cert", "cmk", "encryption", "vault"),
        ("secret-store", "managed-certificate"),
    ),
    (
        ("aks", "kubernetes", "k8s", "pod", "container", "cluster", "kube"),
        (
            "kubernetes-cluster",
            "kubernetes-node-pool",
            "compute.container-app",
            "container-registry",
        ),
    ),
    (
        ("sql", "postgres", "database", "db", "mysql", "cosmos", "redis"),
        ("postgresql-server",),
    ),
    (
        ("vm", "virtualmachine", "compute", "machine", "linux", "windows", "extension", "arc"),
        ("compute.vm", "compute.vm-scale-set", "compute.vm-extension"),
    ),
    (
        ("log", "monitor", "diagnostic", "insight", "alert", "metric", "audit", "workspace"),
        ("log-workspace", "application-insights", "anomaly-alert-rule", "data-collection-rule"),
    ),
    (
        ("role", "rbac", "identity", "auth", "owner", "admin", "principal"),
        ("authorization.role-assignment", "managed-identity"),
    ),
    (
        ("ai", "openai", "cognitive", "ml", "model", "llm", "foundry"),
        ("llm-endpoint", "llm-model-deployment", "ai-project"),
    ),
)

_CATEGORY_FALLBACKS: dict[str, tuple[str, ...]] = {
    "security": (
        "network.nsg",
        "secret-store",
        "authorization.role-assignment",
        "kubernetes-cluster",
    ),
    "compliance": (
        "resource-group",
        "subscription",
        "authorization.role-assignment",
        "secret-store",
    ),
    "reliability": (
        "kubernetes-cluster",
        "compute.container-app",
        "postgresql-server",
        "object-storage",
    ),
    "cost": ("compute.vm", "disk", "object-storage", "network.public-ip"),
    "performance": ("kubernetes-node-pool", "compute.vm-scale-set", "compute.container-app"),
    "operations": ("log-workspace", "application-insights", "resource-group", "subscription"),
    "config_drift": ("resource-group", "kubernetes-cluster", "network.nsg"),
}


def resolve_rule_inventory_types(
    rule: Mapping[str, object],
    available_types: AbstractSet[str],
) -> tuple[str, ...]:
    """Map a Rule's resource_type, applies_to, and domain context to active inventory types."""
    if not available_types:
        return ()

    candidates: list[str] = []
    raw_rt = str(rule.get("resource_type") or "").strip().lower()
    applies_to = rule.get("applies_to")
    extra_types: list[str] = []
    if isinstance(applies_to, Mapping):
        rt_list = applies_to.get("resource_types")
        if isinstance(rt_list, list):
            extra_types.extend(str(item).strip().lower() for item in rt_list if item)

    for rt in (raw_rt, *extra_types):
        if not rt:
            continue
        if rt in available_types and rt not in candidates:
            candidates.append(rt)
        if rt in _EXACT_TYPE_ALIASES:
            for mapped in _EXACT_TYPE_ALIASES[rt]:
                if mapped in available_types and mapped not in candidates:
                    candidates.append(mapped)
        for prefixes, mapped_tuple in _PREFIX_TYPE_ALIASES:
            if any(rt.startswith(prefix) for prefix in prefixes):
                for mapped in mapped_tuple:
                    if mapped in available_types and mapped not in candidates:
                        candidates.append(mapped)

    if candidates:
        return tuple(candidates)

    haystack = " ".join(
        (
            raw_rt,
            str(rule.get("id") or ""),
            str(rule.get("title") or ""),
            str(rule.get("remediates") or ""),
        )
    ).lower()
    for keywords, mapped_tuple in _KEYWORD_FALLBACKS:
        if any(keyword in haystack for keyword in keywords):
            for mapped in mapped_tuple:
                if mapped in available_types and mapped not in candidates:
                    candidates.append(mapped)
    if candidates:
        return tuple(candidates)

    category = str(rule.get("category") or "").strip().lower()
    for mapped in _CATEGORY_FALLBACKS.get(category, ("resource-group", "subscription")):
        if mapped in available_types and mapped not in candidates:
            candidates.append(mapped)

    if not candidates:
        for fallback in ("resource-group", "subscription"):
            if fallback in available_types:
                candidates.append(fallback)
    return tuple(candidates)


def _resource_display_name(resource_id: str, props: Mapping[str, object] | None) -> str:
    if isinstance(props, Mapping):
        name = props.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    leaf = resource_id.rstrip("/").rsplit("/", 1)[-1]
    return leaf or resource_id


def _resource_group_name(resource_id: str, props: Mapping[str, object] | None) -> str | None:
    if isinstance(props, Mapping):
        for key in ("resource_group", "resourceGroup"):
            val = props.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    match = _RG_PATTERN.search(resource_id)
    if match:
        return match.group(1) or match.group(2)
    return None


def _bounded_ref(prefix: str, value: str) -> str:
    candidate = f"{prefix}:{value}"
    normalized = candidate.replace(":", "").replace(".", "").replace("-", "").replace("_", "")
    if len(candidate) <= 160 and normalized.isalnum() and candidate[0].islower():
        return candidate
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


async def read_active_inventory_summary_by_type(
    store: object,
) -> dict[str, dict[str, object]]:
    """Read active inventory resource counts and top resource names grouped by resource_type."""
    fetch_all = getattr(store, "_fetch_all", None)
    if not callable(fetch_all):
        return {}
    try:
        rows = await fetch_all(
            _EFFECTIVE_RESOURCES_CTE + "SELECT resource_type, "
            "COUNT(*)::int AS total_count, "
            " (ARRAY_AGG(COALESCE(NULLIF(props ->> 'name', ''), resource_id) "
            "  ORDER BY COALESCE(NULLIF(props ->> 'name', ''), resource_id), resource_id))[1:5] "
            "  AS sample_names "
            "FROM effective_resources "
            "GROUP BY resource_type",
            {},
        )
    except Exception:
        return {}
    summary: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        rt = str(row.get("resource_type") or "").strip()
        cnt = row.get("total_count")
        if not rt or isinstance(cnt, bool) or not isinstance(cnt, int) or cnt <= 0:
            continue
        raw_names = row.get("sample_names")
        names = (
            [str(n) for n in raw_names if isinstance(n, str) and n.strip()][:_MAX_SAMPLE_NAMES]
            if isinstance(raw_names, list)
            else []
        )
        summary[rt] = {
            "count": cnt,
            "sample_names": names,
        }
    return summary


def enrich_rule_catalog_payload(
    payload: dict[str, object],
    inventory_by_type: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Attach related inventory resource counts and sample names to Rule list/detail payloads."""
    if not inventory_by_type:
        return payload
    available_types = frozenset(inventory_by_type.keys())

    def _enrich_item(item: Mapping[str, object]) -> dict[str, object]:
        matched_types = resolve_rule_inventory_types(item, available_types)
        total_count = 0
        sample_names: list[str] = []
        for rt in matched_types:
            entry = inventory_by_type.get(rt)
            if not isinstance(entry, Mapping):
                continue
            cnt = entry.get("count")
            if isinstance(cnt, int) and not isinstance(cnt, bool):
                total_count += cnt
            names = entry.get("sample_names")
            if isinstance(names, list):
                for name in names:
                    if (
                        isinstance(name, str)
                        and name not in sample_names
                        and len(sample_names) < _MAX_SAMPLE_NAMES
                    ):
                        sample_names.append(name)
        return {
            **item,
            "related_resource_count": total_count,
            "related_resource_names": sample_names,
            "related_resource_types": list(matched_types),
        }

    rules_value = payload.get("rules")
    if isinstance(rules_value, list):
        return {
            **payload,
            "rules": [
                _enrich_item(item) if isinstance(item, Mapping) else item for item in rules_value
            ],
        }
    if isinstance(payload.get("id"), str) and isinstance(payload.get("origin"), str):
        return _enrich_item(payload)
    return payload


async def _read_rule_baseline_outcomes(
    store: object,
    rule_id: str,
) -> dict[str, dict[str, object]]:
    """Read Forseti baseline evaluation outcomes for one Rule keyed by resource_ref."""
    read_state_page = getattr(store, "read_state_page", None)
    if not callable(read_state_page):
        return {}
    try:
        coverage_page = await read_state_page(
            prefix=BASELINE_EVALUATION_LATEST_COVERAGE_KEY,
            limit=1,
        )
        if not coverage_page.records:
            return {}
        cov = coverage_page.records[0].value
        if not isinstance(cov, Mapping):
            return {}
        gen_digest = cov.get("generation_digest")
        if not isinstance(gen_digest, str) or not gen_digest:
            return {}
        outcome_page = await read_state_page(
            prefix=BASELINE_EVALUATION_OUTCOME_PREFIX,
            limit=1_000,
            match_field="generation_digest",
            match_value=gen_digest,
        )
    except Exception:
        return {}

    target_rule_ref = _bounded_ref("rule", rule_id)
    by_resource_ref: dict[str, dict[str, object]] = {}
    for record in outcome_page.records:
        val = record.value
        if not isinstance(val, Mapping):
            continue
        if val.get("rule_ref") != target_rule_ref and val.get("rule_ref") != f"rule:{rule_id}":
            continue
        res_ref = val.get("resource_ref")
        if isinstance(res_ref, str) and res_ref:
            by_resource_ref[res_ref] = dict(val)
    return by_resource_ref


async def derive_rule_findings_payload(
    store: object,
    detail: Mapping[str, object],
) -> dict[str, object] | None:
    """Resolve actual related inventory resources and baseline outcomes for a Rule."""
    fetch_all = getattr(store, "_fetch_all", None)
    if not callable(fetch_all):
        return None
    rule_id = str(detail.get("id") or "")
    origin = str(detail.get("origin") or "active")
    severity = str(detail.get("severity") or "medium")
    if not rule_id:
        return None

    summary_by_type = await read_active_inventory_summary_by_type(store)
    if not summary_by_type:
        return None

    available_types = frozenset(summary_by_type.keys())
    matched_types = resolve_rule_inventory_types(detail, available_types)
    if not matched_types:
        return {
            "rule_id": rule_id,
            "origin": origin,
            "evaluated": True,
            "finding_count": 0,
            "violated_count": 0,
            "compliant_count": 0,
            "abstained_count": 0,
            "observed_count": 0,
            "matched_resource_types": [],
            "findings": [],
        }

    total_count = 0
    for rt in matched_types:
        rt_entry = summary_by_type.get(rt)
        if isinstance(rt_entry, Mapping):
            rt_cnt = rt_entry.get("count")
            if isinstance(rt_cnt, int) and not isinstance(rt_cnt, bool):
                total_count += rt_cnt
    try:
        rows = await fetch_all(
            _EFFECTIVE_RESOURCES_CTE + "SELECT resource_id, resource_type, props, last_seen "
            "FROM effective_resources "
            "WHERE resource_type = ANY(%(matched_types)s) "
            "ORDER BY COALESCE(NULLIF(props ->> 'name', ''), resource_id), resource_id "
            "LIMIT %(limit)s",
            {
                "matched_types": list(matched_types),
                "limit": _MAX_RELATED_RESOURCES,
            },
        )
    except Exception:
        return None

    outcomes_by_ref = await _read_rule_baseline_outcomes(store, rule_id)
    status_rank = {"violated": 0, "abstained": 1, "compliant": 2, "observed": 3}
    findings: list[dict[str, Any]] = []
    counts = {"violated": 0, "compliant": 0, "abstained": 0, "observed": 0}

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        resource_id = str(row.get("resource_id") or "")
        resource_type = str(row.get("resource_type") or "")
        raw_props = row.get("props")
        props = raw_props if isinstance(raw_props, Mapping) else {}
        last_seen = row.get("last_seen")
        observed_at = (
            last_seen.isoformat()
            if isinstance(last_seen, datetime)
            else str(last_seen)
            if isinstance(last_seen, str) and last_seen
            else None
        )
        res_ref = _bounded_ref("resource", resource_id)
        outcome_rec = outcomes_by_ref.get(res_ref)
        status = "observed"
        reason_code: str | None = None
        if isinstance(outcome_rec, Mapping):
            raw_outcome = str(outcome_rec.get("outcome") or "").lower()
            if raw_outcome in {"violated", "compliant", "abstained"}:
                status = raw_outcome
            rc = outcome_rec.get("reason_code")
            if isinstance(rc, str) and rc:
                reason_code = rc
            eval_at = outcome_rec.get("evaluated_at")
            if isinstance(eval_at, str) and eval_at:
                observed_at = eval_at

        counts[status] = counts.get(status, 0) + 1
        resource_name = _resource_display_name(resource_id, props)
        resource_group = _resource_group_name(resource_id, props)
        location = (
            str(props["location"]).strip()
            if isinstance(props.get("location"), str) and str(props["location"]).strip()
            else None
        )
        findings.append(
            {
                "resource_id": resource_id,
                "resource_name": resource_name,
                "resource_type": resource_type,
                "resource_group": resource_group,
                "location": location,
                "status": status,
                "severity": severity,
                "reason_code": reason_code,
                "observed_at": observed_at,
            }
        )

    findings.sort(
        key=lambda item: (
            status_rank.get(str(item.get("status")), 9),
            str(item.get("resource_name") or ""),
            str(item.get("resource_id") or ""),
        )
    )

    return {
        "rule_id": rule_id,
        "origin": origin,
        "evaluated": True,
        "finding_count": total_count,
        "violated_count": counts["violated"],
        "compliant_count": counts["compliant"],
        "abstained_count": counts["abstained"],
        "observed_count": counts["observed"],
        "matched_resource_types": list(matched_types),
        "findings": findings,
    }
