"""AKS inventory controls for the Azure security posture analyzer."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from fdai.core.security import ControlStatus, SecurityControlObservation
from fdai.delivery.azure.security_posture_helpers import (
    MISSING,
    bool_status,
    control,
    display,
    enabled_string_status,
    lookup,
    mapping,
    optional_bool_status,
    presence_status,
)
from fdai.delivery.azure.security_posture_models import AzureResourceSecurityEvidence
from fdai.shared.providers.inventory import ResourceRecord

_AKS_GUIDANCE: Final[str] = "https://learn.microsoft.com/azure/aks/concepts-security"


def aks_controls(
    record: ResourceRecord,
    *,
    extra: AzureResourceSecurityEvidence,
    assessed_at: datetime,
) -> tuple[SecurityControlObservation, ...]:
    """Evaluate AKS control-plane configuration from one inventory record."""

    props = mapping(record.props.get("properties"))
    sku = mapping(record.props.get("sku"))
    network = mapping(props.get("networkProfile"))
    security = mapping(props.get("securityProfile"))
    workload_identity = mapping(security.get("workloadIdentity"))
    image_cleaner = mapping(security.get("imageCleaner"))
    addons = mapping(props.get("addonProfiles"))
    auto_upgrade = mapping(props.get("autoUpgradeProfile"))
    api_access = mapping(props.get("apiServerAccessProfile"))
    aad_profile = lookup(props, "aadProfile")

    return (
        control(
            record,
            assessed_at,
            "aks-version",
            "Kubernetes version",
            "patching",
            ControlStatus.UNKNOWN,
            "medium",
            display(lookup(props, "kubernetesVersion")),
            "supported release",
            "azure-resource-graph",
            "Version support needs the AKS release and security bulletin feed.",
            validation="Compare the version with the supported release table and advisories.",
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-private-api",
            "Private API server",
            "network",
            bool_status(_private_api(api_access, props)),
            "high",
            display(_private_api(api_access, props)),
            "true",
            "azure-resource-graph",
            "A private API server limits control-plane exposure.",
            remediation="Enable private cluster access with reviewed DNS integration.",
            validation="Verify the public API endpoint is unavailable.",
            priority="high",
            due_days=7,
            compliance=("CIS-AKS-5.4.1",),
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-rbac",
            "Kubernetes RBAC",
            "identity",
            bool_status(lookup(props, "enableRbac")),
            "high",
            display(lookup(props, "enableRbac")),
            "true",
            "azure-resource-graph",
            "RBAC limits Kubernetes authorization by identity and role.",
            remediation="Enable Kubernetes RBAC.",
            validation="Verify least-privilege role assignments with an authorization probe.",
            priority="critical",
            due_days=1,
            compliance=("MCSB-IM-1",),
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-network-policy",
            "Pod network policy",
            "network",
            enabled_string_status(lookup(network, "networkPolicy"), disabled=("", "none")),
            "high",
            display(lookup(network, "networkPolicy")),
            "azure-or-calico",
            "azure-resource-graph",
            "Network policy restricts east-west pod traffic.",
            remediation="Enable a supported network policy and stage namespace policies.",
            validation="Verify denied cross-namespace traffic with a bounded probe.",
            priority="high",
            due_days=7,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-entra-integration",
            "Managed Entra integration",
            "identity",
            presence_status(aad_profile),
            "critical",
            display(aad_profile),
            "configured",
            "azure-resource-graph",
            "Managed Entra integration centralizes cluster authentication.",
            remediation="Enable managed Entra integration and Azure RBAC.",
            validation="Verify group-based access and reject local-only authorization.",
            priority="critical",
            due_days=1,
            compliance=("MCSB-IM-1",),
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-local-accounts",
            "Local accounts disabled",
            "identity",
            bool_status(lookup(props, "disableLocalAccounts")),
            "high",
            display(lookup(props, "disableLocalAccounts")),
            "true",
            "azure-resource-graph",
            "Disabling local accounts removes unmanaged credential paths.",
            remediation="Disable local accounts after validating emergency access.",
            validation="Confirm local credential retrieval is rejected.",
            priority="high",
            due_days=7,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-defender",
            "Runtime threat protection",
            "threat-protection",
            optional_bool_status(extra.defender_enabled),
            "high",
            display(extra.defender_enabled),
            "true",
            "defender-for-cloud",
            "Defender coverage supplies runtime threat detection and recommendations.",
            remediation="Enable container threat protection for the monitored scope.",
            validation="Verify healthy Defender assessment and sensor coverage.",
            priority="high",
            due_days=7,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-workload-identity",
            "Workload identity",
            "identity",
            bool_status(lookup(workload_identity, "enabled")),
            "medium",
            display(lookup(workload_identity, "enabled")),
            "true",
            "azure-resource-graph",
            "Workload identity removes long-lived pod credentials.",
            remediation="Enable workload identity and migrate pod credentials.",
            validation="Verify federated token exchange from a test service account.",
            priority="medium",
            due_days=30,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-image-cleaner",
            "Image cleaner",
            "supply-chain",
            _image_cleaner_status(image_cleaner, security),
            "medium",
            display(lookup(image_cleaner, "enabled")),
            "true",
            "azure-resource-graph",
            "Image cleanup reduces stale vulnerable image exposure.",
            remediation="Enable image cleaner with a reviewed interval.",
            validation="Verify unused images are removed after the configured interval.",
            priority="medium",
            due_days=30,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-policy-addon",
            "Azure Policy add-on",
            "governance",
            _addon_status(addons, "azurepolicy"),
            "medium",
            _addon_value(addons, "azurepolicy"),
            "enabled",
            "azure-resource-graph",
            "Policy compliance provides deterministic configuration evaluation.",
            remediation="Enable the policy add-on and assign the approved baseline.",
            validation="Verify compliance state for the baseline controls.",
            priority="medium",
            due_days=30,
            compliance=("MCSB-GV-1",),
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-auto-upgrade",
            "Automatic upgrade channel",
            "patching",
            enabled_string_status(lookup(auto_upgrade, "upgradeChannel"), disabled=("", "none")),
            "medium",
            display(lookup(auto_upgrade, "upgradeChannel")),
            "configured",
            "azure-resource-graph",
            "An upgrade channel shortens exposure to fixed control-plane releases.",
            remediation="Select a reviewed automatic upgrade channel.",
            validation="Verify the channel and maintenance window.",
            priority="medium",
            due_days=30,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-node-os-upgrade",
            "Node OS upgrade channel",
            "patching",
            enabled_string_status(
                lookup(auto_upgrade, "nodeOSUpgradeChannel"), disabled=("", "none")
            ),
            "medium",
            display(lookup(auto_upgrade, "nodeOSUpgradeChannel")),
            "configured",
            "azure-resource-graph",
            "A node OS channel keeps host security fixes moving.",
            remediation="Configure a reviewed node OS upgrade channel.",
            validation="Verify node image rollout after the maintenance window.",
            priority="medium",
            due_days=30,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-service-tier",
            "SLA-backed service tier",
            "resilience",
            _tier_status(lookup(sku, "tier")),
            "medium",
            display(lookup(sku, "tier")),
            "standard-or-higher",
            "azure-resource-graph",
            "The free tier has no production control-plane SLA.",
            remediation="Use an SLA-backed tier for production scope.",
            validation="Verify the configured tier and availability objective.",
            priority="medium",
            due_days=30,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-container-insights",
            "Container Insights",
            "monitoring",
            _addon_status(addons, "omsagent"),
            "medium",
            _addon_value(addons, "omsagent"),
            "enabled",
            "azure-resource-graph",
            "Container Insights supplies workload and node evidence.",
            remediation="Enable Container Insights with managed authentication.",
            validation="Verify recent pod and node telemetry in the workspace.",
            priority="high",
            due_days=7,
            compliance=("MCSB-LT-1",),
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-diagnostics",
            "Platform diagnostic settings",
            "monitoring",
            optional_bool_status(extra.diagnostic_settings_enabled),
            "medium",
            display(extra.diagnostic_settings_enabled),
            "true",
            "azure-monitor-diagnostic-settings",
            "Platform logs support control-plane investigation and audit.",
            remediation="Route approved AKS diagnostic categories to the evidence store.",
            validation="Generate a test event and verify its retained record.",
            priority="high",
            due_days=7,
            compliance=("MCSB-LT-3",),
            source_url=_AKS_GUIDANCE,
        ),
    )


def _private_api(api_access: Mapping[str, Any], props: Mapping[str, Any]) -> object:
    explicit = lookup(api_access, "enablePrivateCluster")
    if explicit is not MISSING:
        return explicit
    private_fqdn = lookup(props, "privateFqdn")
    if private_fqdn is not MISSING:
        return bool(private_fqdn)
    return MISSING


def _addon_status(addons: Mapping[str, Any], name: str) -> ControlStatus:
    return bool_status(lookup(mapping(addons.get(name)), "enabled"))


def _addon_value(addons: Mapping[str, Any], name: str) -> str:
    return display(lookup(mapping(addons.get(name)), "enabled"))


def _image_cleaner_status(
    image_cleaner: Mapping[str, Any], security: Mapping[str, Any]
) -> ControlStatus:
    enabled = lookup(image_cleaner, "enabled")
    if enabled is not MISSING:
        return bool_status(enabled)
    interval = lookup(security, "imageCleanerIntervalHours")
    if interval is MISSING:
        return ControlStatus.UNKNOWN
    if isinstance(interval, int) and not isinstance(interval, bool) and interval > 0:
        return ControlStatus.PASS
    return ControlStatus.FAIL


def _tier_status(value: object) -> ControlStatus:
    if value is MISSING:
        return ControlStatus.UNKNOWN
    return ControlStatus.WARNING if str(value).lower() == "free" else ControlStatus.PASS


__all__ = ["aks_controls"]
