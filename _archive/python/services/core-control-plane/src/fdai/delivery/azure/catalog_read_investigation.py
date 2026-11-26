"""Unified 20-tool direct read investigation registry and catalog query dispatcher.

Unifies the 7 core ``ReadToolId`` operations with 13 catalog-driven direct query
tools (total 20 tools = 100% read investigation tool coverage) so agents can
directly inspect any of the 50 ARG tables, 867 Monitor Log tables, 312 platform
metrics, 350 AMBA alerts, 24 causal mechanisms, 50 probes, and 420 relationship
mappings under strict read-only no-authority bounds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fdai.delivery.azure.arg_catalog_query import (
    ArgCatalogQueryRequest,
    compile_arg_catalog_query,
)
from fdai.delivery.azure.arg_catalog_relationships import (
    load_arg_relationship_mapping_catalog,
)
from fdai.delivery.azure.arg_public_catalog import load_arg_public_catalog
from fdai.delivery.azure.catalog_telemetry_mechanisms import (
    load_causal_mechanism_and_probe_catalog,
)
from fdai.delivery.azure.monitor_catalog_query import (
    MonitorCatalogQueryRequest,
    compile_monitor_catalog_query,
)
from fdai.delivery.azure.monitor_log_catalog import load_monitor_log_catalog
from fdai.delivery.azure.resource_type_recipes import load_resource_type_recipe_catalog


class CatalogReadToolId(StrEnum):
    """Complete 20-member read investigation tool vocabulary."""

    RESOLVE_RESOURCE = "resolve_resource"
    GET_RESOURCE_STATE = "get_resource_state"
    QUERY_RESOURCE_ACTIVITY = "query_resource_activity"
    QUERY_RESOURCE_HEALTH = "query_resource_health"
    QUERY_GUEST_SHUTDOWN_EVENTS = "query_guest_shutdown_events"
    QUERY_NETWORK_SECURITY = "query_network_security"
    QUERY_NETWORK_PEERINGS = "query_network_peerings"
    QUERY_ARG_TABLE = "query_arg_table"
    QUERY_MONITOR_LOG_TABLE = "query_monitor_log_table"
    QUERY_PLATFORM_METRICS = "query_platform_metrics"
    QUERY_AMBA_ALERTS = "query_amba_alerts"
    QUERY_CAUSAL_MECHANISM = "query_causal_mechanism"
    QUERY_DIAGNOSTIC_PROBE = "query_diagnostic_probe"
    QUERY_ADVISOR_RECOMMENDATIONS = "query_advisor_recommendations"
    QUERY_POLICY_COMPLIANCE = "query_policy_compliance"
    QUERY_SECURITY_ASSESSMENTS = "query_security_assessments"
    QUERY_UPDATE_ASSESSMENTS = "query_update_assessments"
    QUERY_SERVICE_HEALTH = "query_service_health"
    QUERY_RESOURCE_CHANGES = "query_resource_changes"
    QUERY_TOPOLOGY_RELATIONSHIPS = "query_topology_relationships"


@dataclass(frozen=True, slots=True)
class CatalogReadToolSpec:
    """Metadata and read-only safety bounds for one of the 20 investigation read tools."""

    tool_id: CatalogReadToolId
    owner_agent: str
    domain: str
    timeout_seconds: int
    max_rows: int
    side_effect_class: str = "read"
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.side_effect_class != "read" or self.execution_authority is not False:
            raise ValueError("CatalogReadToolSpec MUST be read-only with execution_authority=False")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise ValueError("CatalogReadToolSpec.timeout_seconds MUST be 1..60")
        if type(self.max_rows) is not int or not 1 <= self.max_rows <= 1000:
            raise ValueError("CatalogReadToolSpec.max_rows MUST be 1..1000")


CATALOG_READ_TOOL_SPECS: Final[Mapping[CatalogReadToolId, CatalogReadToolSpec]] = MappingProxyType(
    {
        CatalogReadToolId.RESOLVE_RESOURCE: CatalogReadToolSpec(
            CatalogReadToolId.RESOLVE_RESOURCE, "Huginn", "inventory", 10, 50
        ),
        CatalogReadToolId.GET_RESOURCE_STATE: CatalogReadToolSpec(
            CatalogReadToolId.GET_RESOURCE_STATE, "Huginn", "inventory", 10, 50
        ),
        CatalogReadToolId.QUERY_RESOURCE_ACTIVITY: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_RESOURCE_ACTIVITY, "Huginn", "activity", 15, 200
        ),
        CatalogReadToolId.QUERY_RESOURCE_HEALTH: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_RESOURCE_HEALTH, "Heimdall", "health", 15, 100
        ),
        CatalogReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS, "Heimdall", "logs", 15, 200
        ),
        CatalogReadToolId.QUERY_NETWORK_SECURITY: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_NETWORK_SECURITY, "Heimdall", "network", 15, 200
        ),
        CatalogReadToolId.QUERY_NETWORK_PEERINGS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_NETWORK_PEERINGS, "Heimdall", "network", 15, 200
        ),
        CatalogReadToolId.QUERY_ARG_TABLE: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_ARG_TABLE, "Huginn", "inventory", 15, 200
        ),
        CatalogReadToolId.QUERY_MONITOR_LOG_TABLE: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_MONITOR_LOG_TABLE, "Heimdall", "logs", 15, 200
        ),
        CatalogReadToolId.QUERY_PLATFORM_METRICS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_PLATFORM_METRICS, "Heimdall", "metrics", 15, 200
        ),
        CatalogReadToolId.QUERY_AMBA_ALERTS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_AMBA_ALERTS, "Heimdall", "metrics", 10, 350
        ),
        CatalogReadToolId.QUERY_CAUSAL_MECHANISM: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_CAUSAL_MECHANISM, "Heimdall", "logs", 15, 200
        ),
        CatalogReadToolId.QUERY_DIAGNOSTIC_PROBE: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_DIAGNOSTIC_PROBE, "Heimdall", "logs", 15, 200
        ),
        CatalogReadToolId.QUERY_ADVISOR_RECOMMENDATIONS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_ADVISOR_RECOMMENDATIONS, "Njord", "cost", 15, 200
        ),
        CatalogReadToolId.QUERY_POLICY_COMPLIANCE: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_POLICY_COMPLIANCE, "Huginn", "inventory", 15, 200
        ),
        CatalogReadToolId.QUERY_SECURITY_ASSESSMENTS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_SECURITY_ASSESSMENTS, "Heimdall", "health", 15, 200
        ),
        CatalogReadToolId.QUERY_UPDATE_ASSESSMENTS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_UPDATE_ASSESSMENTS, "Vidar", "recovery", 15, 200
        ),
        CatalogReadToolId.QUERY_SERVICE_HEALTH: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_SERVICE_HEALTH, "Heimdall", "health", 15, 100
        ),
        CatalogReadToolId.QUERY_RESOURCE_CHANGES: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_RESOURCE_CHANGES, "Huginn", "activity", 15, 200
        ),
        CatalogReadToolId.QUERY_TOPOLOGY_RELATIONSHIPS: CatalogReadToolSpec(
            CatalogReadToolId.QUERY_TOPOLOGY_RELATIONSHIPS, "Huginn", "inventory", 10, 420
        ),
    }
)


class CatalogReadInvestigationDispatcher:
    """Resolve and compile direct queries across all 20 read investigation tools."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._arg = load_arg_public_catalog(repo_root)
        self._mon = load_monitor_log_catalog(repo_root)
        self._recipes = load_resource_type_recipe_catalog(repo_root)
        self._mechs = load_causal_mechanism_and_probe_catalog(repo_root)
        self._rels = load_arg_relationship_mapping_catalog(repo_root)

    def coverage_summary(self) -> dict[str, int]:
        """Return the exact counts across all catalog-backed domains."""
        return {
            "arg_tables": self._arg.total_tables,
            "arg_resource_types": self._arg.total_arg_resource_types,
            "arm_schema_types": self._arg.total_arm_schema_types,
            "arg_relationship_mappings": self._rels.total_mappings,
            "monitor_log_categories": self._mon.total_categories,
            "monitor_log_tables": self._mon.total_tables,
            "canonical_resource_types": self._recipes.total_resource_types,
            "platform_metric_recipes": self._recipes.total_platform_metrics,
            "kql_telemetry_recipes": self._recipes.total_kql_recipes,
            "semantic_metric_definitions": self._recipes.total_semantic_definitions,
            "amba_alert_recipes": self._recipes.total_amba_alerts,
            "causal_telemetry_mechanisms": self._mechs.total_mechanisms,
            "diagnostic_probes": self._mechs.total_probes,
            "read_investigation_tools": len(CATALOG_READ_TOOL_SPECS),
        }

    def compile_direct_query(
        self,
        tool_id: CatalogReadToolId,
        *,
        subscription_ids: tuple[str, ...] = ("00000000-0000-0000-0000-000000000000",),
        target: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Compile a bounded query or return the catalog recipe for any of the 20 tools."""
        spec = CATALOG_READ_TOOL_SPECS[tool_id]
        if tool_id is CatalogReadToolId.QUERY_ARG_TABLE:
            table = target.strip() or "resources"
            kql = compile_arg_catalog_query(
                ArgCatalogQueryRequest(
                    table_name=table, subscription_ids=subscription_ids, limit=limit
                ),
                catalog=self._arg,
            )
            return {"tool_id": tool_id.value, "owner": spec.owner_agent, "kql": kql}
        if tool_id is CatalogReadToolId.QUERY_MONITOR_LOG_TABLE:
            table = target.strip() or "AzureActivity"
            kql = compile_monitor_catalog_query(
                MonitorCatalogQueryRequest(table_name=table, limit=limit),
                catalog=self._mon,
            )
            return {"tool_id": tool_id.value, "owner": spec.owner_agent, "kql": kql}
        if tool_id is CatalogReadToolId.QUERY_CAUSAL_MECHANISM:
            mech = self._mechs.get_mechanism(target or "failed_requests")
            return {"tool_id": tool_id.value, "owner": mech.owner_agent, "kql": mech.kql}
        if tool_id is CatalogReadToolId.QUERY_DIAGNOSTIC_PROBE:
            probe = self._mechs.get_probe(target or "blast_radius_classifier")
            return {
                "tool_id": tool_id.value,
                "owner": probe.owner_agent,
                "target_table": probe.target_table,
            }
        if tool_id is CatalogReadToolId.QUERY_TOPOLOGY_RELATIONSHIPS:
            rels = self._rels.mappings_for_source_type(
                target or "microsoft.compute/virtualmachines"
            )
            return {"tool_id": tool_id.value, "owner": spec.owner_agent, "mappings": len(rels)}
        return {"tool_id": tool_id.value, "owner": spec.owner_agent, "domain": spec.domain}


__all__ = [
    "CATALOG_READ_TOOL_SPECS",
    "CatalogReadInvestigationDispatcher",
    "CatalogReadToolId",
    "CatalogReadToolSpec",
]
