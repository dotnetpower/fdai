"""Compile one product profile into authority-neutral Terraform values."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fdai_service_contracts.product_profile import AzureObservationRole, ProductAddOn

from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile

_STEWARD_AGENT_NAMES = (
    "Odin",
    "Thor",
    "Forseti",
    "Huginn",
    "Heimdall",
    "Vidar",
    "Var",
    "Bragi",
    "Saga",
    "Mimir",
    "Muninn",
    "Norns",
    "Njord",
    "Freyr",
)


def product_terraform_values(
    runtime_profile: RuntimeDeploymentProfile,
    entra: dict[str, Any],
    *,
    require_guid: Callable[[dict[str, Any], str], str],
) -> dict[str, object]:
    """Return only bindings selected by the immutable product profile."""

    profile = runtime_profile.product_profile
    console = profile.selects(ProductAddOn.READ_ONLY_CONSOLE)
    governed_execution = profile.selects(ProductAddOn.GOVERNED_EXECUTION)
    notifications = profile.selects(ProductAddOn.NOTIFICATIONS)
    enterprise_identity = profile.selects(ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE)
    permissions = profile.observation_permissions
    values: dict[str, object] = {
        "enable_console": console,
        "enable_operator_api": console or enterprise_identity,
        "enable_isolated_executor": governed_execution,
        "enable_governed_execution": governed_execution,
        "enable_email_notifications": notifications,
        "enable_document_ingestion": console and runtime_profile.runtime_platform.value == "aks",
        "enable_inventory_monitoring_reader": permissions.selects(
            AzureObservationRole.MONITORING_READER
        ),
        "enable_inventory_log_analytics_reader": permissions.selects(
            AzureObservationRole.LOG_ANALYTICS_READER
        ),
        "enable_inventory_cost_management_reader": permissions.selects(
            AzureObservationRole.COST_MANAGEMENT_READER
        ),
        "enable_inventory_aks_reader": permissions.selects(AzureObservationRole.AKS_READ_ONLY),
        "inventory_kubernetes_subscription_discovery_enabled": permissions.selects(
            AzureObservationRole.AKS_READ_ONLY
        ),
        "enable_inventory_evidence_store_reader": permissions.selects(
            AzureObservationRole.EVIDENCE_STORE_DATA_READER
        ),
        "product_profile_json": json.dumps(
            profile.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    if not enterprise_identity:
        return values
    operator_id = require_guid(entra, "CURRENT_OPERATOR_OBJECT_ID")
    values.update(
        operator_api_audience=str(entra["OPERATOR_API_AUDIENCE"]),
        rbac_readers_group_id=str(entra["RBAC_READERS_GROUP_ID"]),
        rbac_contributors_group_id=str(entra["RBAC_CONTRIBUTORS_GROUP_ID"]),
        rbac_approvers_group_id=str(entra["RBAC_APPROVERS_GROUP_ID"]),
        rbac_owners_group_id=str(entra["RBAC_OWNERS_GROUP_ID"]),
        rbac_break_glass_group_id=str(entra["RBAC_BREAK_GLASS_GROUP_ID"]),
        stewardship_maintainers=operator_id,
        stewardship_agent_bindings={name: f"user:{operator_id}" for name in _STEWARD_AGENT_NAMES},
    )
    return values


__all__ = ["product_terraform_values"]
