"""Azure inventory security posture analyzer tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.security import ControlStatus
from fdai.delivery.azure.security_posture import (
    AzureCveEvidence,
    AzureResourceSecurityEvidence,
    analyze_azure_inventory_security,
    controls_to_report_signals,
)
from fdai.shared.providers.inventory import ResourceRecord

_AT = datetime(2026, 7, 18, tzinfo=UTC)


def _aks() -> ResourceRecord:
    return ResourceRecord(
        resource_id="rg-example/aks-example",
        type="kubernetes-cluster",
        provider_ref="azure://rg-example/aks-example",
        props={
            "sku": {"tier": "Free"},
            "properties": {
                "kubernetesVersion": "1.34.7",
                "enableRbac": True,
                "aadProfile": None,
                "disableLocalAccounts": False,
                "privateFqdn": "private.example.invalid",
                "networkProfile": {"networkPolicy": "none"},
                "securityProfile": {
                    "workloadIdentity": {"enabled": True},
                    "imageCleanerIntervalHours": 168,
                },
                "addonProfiles": {
                    "azurepolicy": {"enabled": False},
                    "omsagent": {"enabled": True},
                },
                "autoUpgradeProfile": {
                    "upgradeChannel": None,
                    "nodeOSUpgradeChannel": "NodeImage",
                },
            },
        },
    )


def _node_pool() -> ResourceRecord:
    return ResourceRecord(
        resource_id="rg-example/aks-example/nodepool1",
        type="kubernetes-node-pool",
        provider_ref="azure://rg-example/aks-example/nodepool1",
        props={
            "properties": {
                "nodeImageVersion": "AKSUbuntu-current",
                "securityProfile": {"enableSecureBoot": True, "enableVtpm": False},
            }
        },
    )


def _mysql() -> ResourceRecord:
    return ResourceRecord(
        resource_id="rg-example/mysql-example",
        type="mysql-server",
        provider_ref="azure://rg-example/mysql-example",
        props={
            "sku": {"tier": "Burstable", "name": "Standard_B1ms"},
            "properties": {
                "version": "8.0.21",
                "network": {
                    "publicNetworkAccess": "Disabled",
                    "delegatedSubnetResourceId": "azure://vnet/subnet",
                    "privateDnsZoneResourceId": "azure://dns-zone",
                },
                "backup": {
                    "backupRetentionDays": 7,
                    "geoRedundantBackup": "Disabled",
                },
                "highAvailability": {"mode": "Disabled"},
                "dataEncryption": None,
                "privateEndpointConnections": [],
            },
        },
    )


def _by_id(controls):
    return {control.control_id: control for control in controls}


def test_azure_inventory_and_supplemental_evidence_produce_thirty_controls() -> None:
    supplemental = {
        "rg-example/aks-example": AzureResourceSecurityEvidence(
            defender_enabled=True,
            diagnostic_settings_enabled=True,
        ),
        "rg-example/mysql-example": AzureResourceSecurityEvidence(
            server_parameters={
                "require_secure_transport": "ON",
                "tls_version": "TLSv1.2,TLSv1.3",
                "audit_log_enabled": "OFF",
            },
            diagnostic_settings_enabled=False,
            cves=(
                AzureCveEvidence(
                    cve_id="CVE-2099-0001",
                    applicability="applicable",
                    patch_status="affected",
                    source_url="https://example.com/advisory",
                    managed_service_note="Provider backport state requires confirmation.",
                ),
            ),
        ),
    }
    controls = analyze_azure_inventory_security(
        (_aks(), _node_pool(), _mysql()),
        assessed_at=_AT,
        supplemental=supplemental,
    )
    by_id = _by_id(controls)

    assert len(controls) == 30
    assert by_id["aks-private-api"].status is ControlStatus.PASS
    assert by_id["aks-network-policy"].status is ControlStatus.FAIL
    assert by_id["aks-entra-integration"].status is ControlStatus.FAIL
    assert by_id["aks-defender"].status is ControlStatus.PASS
    assert by_id["aks-image-cleaner"].status is ControlStatus.PASS
    assert by_id["aks-policy-addon"].status is ControlStatus.FAIL
    assert by_id["aks-service-tier"].status is ControlStatus.WARNING
    assert by_id["aks-node-image"].status is ControlStatus.PASS
    assert by_id["aks-node-vtpm"].status is ControlStatus.FAIL
    assert by_id["mysql-version"].status is ControlStatus.FAIL
    assert by_id["mysql-version"].cve_ids == ("CVE-2099-0001",)
    assert by_id["mysql-version"].managed_service_note
    assert by_id["mysql-secure-transport"].status is ControlStatus.PASS
    assert by_id["mysql-tls"].status is ControlStatus.PASS
    assert by_id["mysql-public-access"].status is ControlStatus.PASS
    assert by_id["mysql-backup-retention"].status is ControlStatus.WARNING
    assert by_id["mysql-geo-backup"].status is ControlStatus.FAIL
    assert by_id["mysql-ha"].status is ControlStatus.FAIL
    assert by_id["mysql-audit-log"].status is ControlStatus.FAIL
    assert by_id["mysql-diagnostics"].status is ControlStatus.FAIL
    assert by_id["mysql-service-tier"].status is ControlStatus.WARNING

    signals = controls_to_report_signals(controls)
    assert len(signals) == 30
    mysql_version = next(
        signal for signal in signals if signal.metadata["control_id"] == "mysql-version"
    )
    assert mysql_version.metadata["status"] == "fail"
    assert mysql_version.metadata["cve_ids"] == "CVE-2099-0001"
    assert mysql_version.evidence_refs


def test_missing_supplemental_reads_remain_unknown_not_false_failure() -> None:
    controls = analyze_azure_inventory_security(
        (_aks(), _mysql()),
        assessed_at=_AT,
    )
    by_id = _by_id(controls)

    assert by_id["aks-defender"].status is ControlStatus.UNKNOWN
    assert by_id["aks-diagnostics"].status is ControlStatus.UNKNOWN
    assert by_id["mysql-version"].status is ControlStatus.UNKNOWN
    assert by_id["mysql-secure-transport"].status is ControlStatus.UNKNOWN
    assert by_id["mysql-tls"].status is ControlStatus.UNKNOWN
    assert by_id["mysql-audit-log"].status is ControlStatus.UNKNOWN
    assert by_id["mysql-diagnostics"].status is ControlStatus.UNKNOWN


def test_unrelated_resource_type_is_ignored() -> None:
    controls = analyze_azure_inventory_security(
        (ResourceRecord(resource_id="vm-1", type="compute.vm"),),
        assessed_at=_AT,
    )
    assert controls == ()
