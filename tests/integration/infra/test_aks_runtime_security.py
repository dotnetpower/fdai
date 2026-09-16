from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("resource_type", "resource_name", "settings"),
    [
        (
            "azurerm_kubernetes_cluster",
            "runtime",
            {
                "azure_policy_enabled": "true",
                "private_cluster_enabled": "var.private_cluster_enabled",
                "local_account_disabled": "true",
                "role_based_access_control_enabled": "true",
                "automatic_upgrade_channel": '"patch"',
                "node_os_upgrade_channel": '"NodeImage"',
                "host_encryption_enabled": "true",
                "os_disk_type": '"Managed"',
                "max_pods": "50",
                "outbound_type": '"userAssignedNATGateway"',
            },
        ),
        (
            "azurerm_kubernetes_cluster_node_pool",
            "user",
            {
                "host_encryption_enabled": "true",
                "os_disk_type": '"Managed"',
                "max_pods": "50",
            },
        ),
    ],
)
def test_aks_security_controls_use_current_provider_attributes(
    resource_type: str, resource_name: str, settings: dict[str, str]
) -> None:
    source = (ROOT / "infra/runtimes/aks/cluster/main.tf").read_text(encoding="utf-8")
    resource = f'resource "{resource_type}" "{resource_name}"'
    start = source.index(resource)
    block = source[start : source.index("\n}", start) + 2]

    for attribute, expected in settings.items():
        assert re.search(rf"(?m)^\s*{attribute}\s*=\s*{re.escape(expected)}\s*$", block), attribute


def test_aks_existing_subnet_has_explicit_egress_before_cluster_creation() -> None:
    source = (ROOT / "infra/runtimes/aks/cluster/main.tf").read_text(encoding="utf-8")
    public_ip = source[
        source.index('resource "azurerm_public_ip" "egress"') : source.index(
            'resource "azurerm_nat_gateway" "egress"'
        )
    ]
    assert 'resource "azurerm_nat_gateway" "egress"' in source
    assert 'resource "azurerm_subnet_nat_gateway_association" "egress"' in source
    assert 'resource "azurerm_nat_gateway_public_ip_association" "egress"' in source
    assert "tags                = local.tags" in public_ip
    assert "ignore_changes = [ip_tags]" in public_ip
    assert "subnet_id      = var.aks_subnet_id" in source
    assert "nat_gateway_id = azurerm_nat_gateway.egress.id" in source
    assert "azurerm_nat_gateway_public_ip_association.egress," in source
    assert "azurerm_subnet_nat_gateway_association.egress," in source
    assert '"managedNATGateway"' not in source


def test_aks_baseline_uses_api_server_vnet_integration() -> None:
    cluster = (ROOT / "infra/runtimes/aks/cluster/main.tf").read_text(encoding="utf-8")
    network = (ROOT / "infra/modules/network/main.tf").read_text(encoding="utf-8")
    substrate = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    outputs = (ROOT / "infra/outputs.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_subnet" "aks_api_server"' in network
    assert 'name    = "Microsoft.ContainerService/managedClusters"' in network
    assert re.search(
        r'count\s*=\s*var\.enable_private_networking \|\| var\.compute_kind == "aks" \? 1 : 0',
        substrate,
    )
    assert re.search(r'var\.compute_kind == "aks" \? module\.network\[0\]\.aks_subnet_id', outputs)
    assert re.search(
        r'var\.compute_kind == "aks" \? module\.network\[0\]\.aks_api_server_subnet_id',
        outputs,
    )
    assert "virtual_network_integration_enabled = true" in cluster
    assert re.search(r"subnet_id\s*=\s*var\.aks_api_server_subnet_id", cluster)
    assert re.search(r"authorized_ip_ranges\s*=\s*var\.api_server_authorized_ip_ranges", cluster)
    assert re.search(r"private_cluster_enabled\s*=\s*var\.private_cluster_enabled", cluster)
    assert "#trivy:ignore:AZU-0065" in cluster
    assert "checkov:skip=CKV_AZURE_115" in cluster
    assert "explicit authorized CIDRs, Entra RBAC, disabled local accounts" in cluster


def test_aks_container_insights_has_dcr_and_cluster_association() -> None:
    cluster = (ROOT / "infra/runtimes/aks/cluster/main.tf").read_text(encoding="utf-8")

    assert 'substr("MSCI-${var.location}-${local.name}", 0, 64)' in cluster
    assert 'resource "azurerm_monitor_data_collection_rule" "container_insights"' in cluster
    assert "workspace_resource_id = var.log_analytics_workspace_id" in cluster
    assert cluster.count('streams        = ["Microsoft-ContainerInsights-Group-Default"]') == 1
    assert cluster.count('streams      = ["Microsoft-ContainerInsights-Group-Default"]') == 1
    assert 'extension_name = "ContainerInsights"' in cluster
    assert re.search(r"(?m)^\s*enableContainerLogV2\s*=\s*true\s*$", cluster)
    assert (
        'resource "azurerm_monitor_data_collection_rule_association" "container_insights"'
        in cluster
    )
    assert 'name                    = "ContainerInsightsExtension"' in cluster
    assert "target_resource_id      = azurerm_kubernetes_cluster.runtime.id" in cluster
    assert (
        "data_collection_rule_id = azurerm_monitor_data_collection_rule.container_insights.id"
        in cluster
    )


def test_aks_document_workloads_have_dedicated_substrate_roles() -> None:
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    outputs = (ROOT / "infra/outputs.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_role_assignment" "ingestion_aks_eventhubs_sender"' in root
    assert 'resource "azurerm_role_assignment" "ingestion_worker_aks_eventhubs_receiver"' in root
    assert 'module.event_bus.auxiliary_topic_ids["fdai.pipeline.stages"]' in root
    assert "ingestion = var.enable_document_ingestion ?" in outputs
    assert "ingestion_worker = var.enable_document_ingestion" in outputs
    assert 'output "document_storage_binding"' in outputs
