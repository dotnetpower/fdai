"""Normalized Rule properties derive only from documented ARM fields and never from absence."""

from __future__ import annotations

from typing import Any

from fdai.delivery.azure.arm_rule_properties import (
    MAX_SECURITY_RULES,
    rule_properties,
)


def _rule(**properties: Any) -> dict[str, Any]:
    return {"name": "rule", "properties": properties}


def test_storage_projects_documented_fields_and_only_approved_private_endpoints() -> None:
    row = {
        "properties": {
            "supportsHttpsTrafficOnly": True,
            "allowSharedKeyAccess": False,
            "minimumTlsVersion": "TLS1_2",
            "publicNetworkAccess": "Disabled",
            "encryption": {"requireInfrastructureEncryption": True},
            "privateEndpointConnections": [
                {"properties": {"privateLinkServiceConnectionState": {"status": "Approved"}}},
                {"properties": {"privateLinkServiceConnectionState": {"status": "Pending"}}},
            ],
        }
    }

    assert rule_properties("object-storage", row) == {
        "enable_https_traffic_only": True,
        "allow_shared_key_access": False,
        "min_tls_version": "TLS1_2",
        "public_network_access_enabled": False,
        "infrastructure_encryption_enabled": True,
        "private_endpoints": [{"status": "Approved"}],
    }


def test_absent_or_unrecognized_fields_stay_unobserved() -> None:
    row = {
        "properties": {
            "publicNetworkAccess": "SecuredByPerimeter",
            "encryption": {},
            "supportsHttpsTrafficOnly": "true",
        }
    }

    assert rule_properties("object-storage", row) == {"infrastructure_encryption_enabled": False}
    assert rule_properties("object-storage", {}) == {}
    assert rule_properties("unmapped.type", {"properties": {"x": 1}}) == {}
    assert rule_properties("compute.vm", {"name": "vm"}) == {}
    assert rule_properties("cache", {"name": "cache"}) == {}


def test_key_vault_purge_protection_absence_means_disabled() -> None:
    enabled = {"properties": {"enablePurgeProtection": True, "enableSoftDelete": True}}
    absent = {"properties": {"enableRbacAuthorization": True, "publicNetworkAccess": "Enabled"}}

    assert rule_properties("secret-store", enabled) == {
        "purge_protection_enabled": True,
        "soft_delete_enabled": True,
    }
    assert rule_properties("secret-store", absent) == {
        "purge_protection_enabled": False,
        "rbac_authorization_enabled": True,
        "public_network_access_enabled": True,
    }


def test_nsg_rules_are_projected_completely_or_not_at_all() -> None:
    rdp = _rule(
        direction="Inbound",
        access="Allow",
        protocol="Tcp",
        destinationPortRange="3389",
        sourceAddressPrefix="*",
    )
    ranged = _rule(
        direction="Inbound",
        access="Deny",
        protocol="*",
        destinationPortRanges=["22", "443"],
        sourceAddressPrefixes=["10.0.0.0/8"],
    )

    projected = rule_properties("network.nsg", {"properties": {"securityRules": [rdp, ranged]}})

    # The ranged rule is a deny, so its lists cannot hide an exposure.
    assert projected["security_rules"] == [
        {
            "direction": "Inbound",
            "access": "Allow",
            "protocol": "Tcp",
            "destination_port_range": "3389",
            "source_address_prefix": "*",
        },
        {
            "direction": "Inbound",
            "access": "Deny",
            "protocol": "*",
            "destination_port_ranges": ["22", "443"],
            "source_address_prefixes": ["10.0.0.0/8"],
        },
    ]
    assert projected["inbound_security_rules"] == projected["security_rules"]
    assert rule_properties("network.nsg", {"properties": {"securityRules": []}}) == {
        "security_rules": [],
        "inbound_security_rules": [],
    }
    unreadable = {"properties": {"securityRules": [rdp, {"name": "broken"}]}}
    assert rule_properties("network.nsg", unreadable) == {}
    oversized = {"properties": {"securityRules": [rdp] * (MAX_SECURITY_RULES + 1)}}
    assert rule_properties("network.nsg", oversized) == {}


def test_inbound_allow_rules_outside_the_exact_vocabulary_stay_unobserved() -> None:
    base = {
        "direction": "Inbound",
        "access": "Allow",
        "protocol": "Tcp",
        "destinationPortRange": "22",
        "sourceAddressPrefix": "10.0.0.0/8",
    }
    exact = rule_properties("network.nsg", {"properties": {"securityRules": [_rule(**base)]}})
    assert exact["security_rules"][0]["destination_port_range"] == "22"
    for change in (
        {"protocol": "*"},
        {"destinationPortRange": "*"},
        {"destinationPortRange": "20-25"},
        {"sourceAddressPrefix": "Internet"},
        {"sourceAddressPrefix": "0.0.0.0/0"},
        {"destinationPortRange": None, "destinationPortRanges": ["22", "3389"]},
        {"sourceAddressPrefix": None, "sourceAddressPrefixes": ["1.2.3.4/32"]},
    ):
        rule = _rule(**{**base, **change})
        projected = rule_properties("network.nsg", {"properties": {"securityRules": [rule]}})
        assert "security_rules" not in projected
        assert len(projected["inbound_security_rules"]) == 1


def test_inbound_security_rules_keep_every_shape_and_priority() -> None:
    allow = {
        **_rule(
            direction="Inbound",
            access="Allow",
            protocol="*",
            destinationPortRanges=["20-25", "3389"],
            sourceAddressPrefix="Internet",
        )
    }
    allow["properties"]["priority"] = 300
    outbound = _rule(direction="Outbound", access="Allow", protocol="Tcp")
    flagged = _rule(direction="Inbound", access="Deny", protocol="Tcp")
    flagged["properties"]["priority"] = True

    projected = rule_properties(
        "network.nsg", {"properties": {"securityRules": [allow, outbound, flagged]}}
    )

    assert "security_rules" not in projected
    assert projected["inbound_security_rules"] == [
        {
            "direction": "Inbound",
            "access": "Allow",
            "protocol": "*",
            "source_address_prefix": "Internet",
            "destination_port_ranges": ["20-25", "3389"],
            "priority": 300,
        },
        {"direction": "Inbound", "access": "Deny", "protocol": "Tcp"},
    ]


def test_identity_and_zones_count_only_when_the_projected_column_is_present() -> None:
    assert rule_properties("compute.vm", {"identity": None}) == {"identity_type": "None"}
    assert rule_properties("compute.vm", {"identity": {"type": "SystemAssigned"}}) == {
        "identity_type": "SystemAssigned"
    }
    assert rule_properties("compute.vm-scale-set", {"zones": ["3", "1"]}) == {"zones": ["1", "3"]}
    assert rule_properties("cache", {"zones": None}) == {"zones": []}
    assert rule_properties(
        "kubernetes-node-pool", {"properties": {"availabilityZones": ["2", "1"]}}
    ) == {"availability_zones": ["1", "2"]}
    assert rule_properties("kubernetes-node-pool", {"properties": {"count": 3}}) == {
        "availability_zones": []
    }
    assert rule_properties("kubernetes-node-pool", {"name": "pool"}) == {}


def test_database_and_cluster_fields() -> None:
    flexible = {
        "properties": {
            "highAvailability": {"mode": "ZoneRedundant"},
            "dataEncryption": {"type": "SystemManaged"},
        }
    }
    single = {"properties": {"sslEnforcement": "Enabled"}}
    cluster = {
        "properties": {
            "networkProfile": {"networkPolicy": "none"},
            "aadProfile": {"enableAzureRBAC": True},
            "apiServerAccessProfile": {"enablePrivateCluster": False},
        }
    }

    assert rule_properties("postgresql-server", flexible) == {
        "ha_mode": "ZoneRedundant",
        "encryption_at_rest_enabled": True,
    }
    assert rule_properties("postgresql-server", single) == {"ssl_enforcement": "enabled"}
    assert rule_properties("sql-database", {"properties": {"zoneRedundant": False}}) == {
        "zone_redundant": False
    }
    assert rule_properties("kubernetes-cluster", cluster) == {
        "network_policy": False,
        "azure_rbac_enabled": True,
        "private_cluster_enabled": False,
        "defender_security_monitoring_enabled": False,
    }
    calico = {"properties": {"networkProfile": {"networkPolicy": "calico"}}}
    assert rule_properties("kubernetes-cluster", calico) == {
        "network_policy": True,
        "defender_security_monitoring_enabled": False,
    }


def test_inbound_security_rules_carry_the_scope_of_each_rule() -> None:
    deny = _rule(
        direction="Inbound",
        access="Deny",
        protocol="*",
        destinationPortRange="3389",
        sourceAddressPrefix="Internet",
        sourcePortRanges=["1-1023"],
        destinationAddressPrefix="10.0.0.4",
        destinationApplicationSecurityGroups=[{"id": "asg"}],
    )

    projected = rule_properties("network.nsg", {"properties": {"securityRules": [deny]}})

    [complete] = projected["inbound_security_rules"]
    assert complete["destination_address_prefix"] == "10.0.0.4"
    assert complete["source_port_ranges"] == ["1-1023"]
    assert complete["destination_application_security_groups"] == 1
    assert "destination_address_prefix" not in projected["security_rules"][0]


def test_aks_defender_profile_absence_means_disabled() -> None:
    enabled = {
        "properties": {"securityProfile": {"defender": {"securityMonitoring": {"enabled": True}}}}
    }
    absent = {"properties": {"securityProfile": {"workloadIdentity": {"enabled": True}}}}
    malformed = {"properties": {"securityProfile": {"defender": "on"}}}

    assert rule_properties("kubernetes-cluster", enabled)["defender_security_monitoring_enabled"]
    assert rule_properties("kubernetes-cluster", absent) == {
        "defender_security_monitoring_enabled": False
    }
    assert "defender_security_monitoring_enabled" not in rule_properties(
        "kubernetes-cluster", malformed
    )


def test_vm_encryption_at_host_projects_only_for_standalone_vms() -> None:
    standalone = {
        "type": "Microsoft.Compute/virtualMachines",
        "properties": {"securityProfile": {"securityType": "TrustedLaunch"}},
    }
    enabled = {
        "type": "Microsoft.Compute/virtualMachines",
        "properties": {"securityProfile": {"encryptionAtHost": True}},
    }
    instance = {
        "type": "Microsoft.Compute/virtualMachineScaleSets/virtualMachines",
        "properties": {},
    }

    assert rule_properties("compute.vm", standalone) == {"encryption_at_host_enabled": False}
    assert rule_properties("compute.vm", enabled) == {"encryption_at_host_enabled": True}
    assert rule_properties("compute.vm", instance) == {}


def test_postgresql_flexible_auth_modes_project_only_documented_states() -> None:
    row = {
        "properties": {"authConfig": {"activeDirectoryAuth": "Enabled", "passwordAuth": "Disabled"}}
    }
    unknown = {"properties": {"authConfig": {"activeDirectoryAuth": "Pending"}}}

    assert rule_properties("postgresql-server", row) == {
        "entra_auth_enabled": True,
        "password_auth_enabled": False,
    }
    assert rule_properties("postgresql-server", unknown) == {}
