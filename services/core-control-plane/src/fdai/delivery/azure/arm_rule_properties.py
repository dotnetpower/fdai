"""Project reviewed Azure Resource Manager fields onto the normalized properties Rules evaluate.

Shipped Rules read provider-neutral properties such as ``enable_https_traffic_only`` or
``security_rules`` (see ``rule-catalog/vocabulary/property-semantics.yaml``). Azure inventory rows
carry the raw ARM payload instead, so this adapter derives each normalized property from one
documented ARM field. It never infers a value from a missing field: an absent source leaves the
normalized property absent, and Forseti then records the pair as ``property_unobserved`` rather
than compliant. The documented exceptions are ARM fields omitted in their default state: Key Vault
purge protection, AKS node pool zones, storage infrastructure encryption, and blob versioning. Each
default is the non-compliant value, so it can only make a Rule deny, never pass.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

MAX_SECURITY_RULES = 1_000
MAX_PROJECTED_BYTES = 131_072

_Projector = Callable[[Mapping[str, Any]], dict[str, Any]]
_ANY_SOURCE_ALIASES = frozenset({"internet", "0.0.0.0/0", "any", "::/0"})


def rule_properties(resource_type: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the normalized Rule properties derivable from one complete ARM or ARG row.

    ``row`` is the provider row before truncation. Top-level ``identity`` and ``zones`` count as
    observed only when the row carries the key, which the reviewed ARG projection always does.
    The result is bounded; a projection over ``MAX_PROJECTED_BYTES`` is dropped entirely.
    """

    projector = _PROJECTORS.get(resource_type)
    if projector is None:
        return {}
    projected = projector(row)
    encoded = json.dumps(projected, default=str, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PROJECTED_BYTES:
        return {}
    return projected


def _properties(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = row.get("properties")
    return value if isinstance(value, Mapping) else None


def _set_bool(target: dict[str, Any], key: str, value: object) -> None:
    if isinstance(value, bool):
        target[key] = value


def _set_text(target: dict[str, Any], key: str, value: object) -> None:
    if isinstance(value, str) and value.strip():
        target[key] = value.strip()


def _public_network_access(target: dict[str, Any], value: object) -> None:
    # Only the two documented states are decisive; perimeter-secured or unknown values stay absent.
    if isinstance(value, str) and value.casefold() in {"enabled", "disabled"}:
        target["public_network_access_enabled"] = value.casefold() == "enabled"


def _zones(target: dict[str, Any], row: Mapping[str, Any], key: str) -> None:
    if "zones" not in row:
        return
    value = row["zones"]
    if value is None:
        target[key] = []
    elif isinstance(value, Sequence) and not isinstance(value, str):
        if all(isinstance(item, str) for item in value):
            target[key] = sorted(value)


def _object_storage(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = _properties(row)
    if properties is None:
        return {}
    projected: dict[str, Any] = {}
    _set_bool(projected, "enable_https_traffic_only", properties.get("supportsHttpsTrafficOnly"))
    _set_bool(projected, "allow_shared_key_access", properties.get("allowSharedKeyAccess"))
    _set_text(projected, "min_tls_version", properties.get("minimumTlsVersion"))
    _public_network_access(projected, properties.get("publicNetworkAccess"))
    encryption = properties.get("encryption")
    if isinstance(encryption, Mapping):
        # ARM omits this create-time flag unless it was set, and it defaults to false. Defaulting
        # can only make the requiring Rule deny, never pass.
        infrastructure = encryption.get("requireInfrastructureEncryption", False)
        _set_bool(projected, "infrastructure_encryption_enabled", infrastructure)
    connections = properties.get("privateEndpointConnections")
    if isinstance(connections, Sequence) and not isinstance(connections, str):
        # Only an approved connection is a usable private endpoint.
        projected["private_endpoints"] = [
            {"status": "Approved"}
            for connection in connections
            if _connection_status(connection) == "approved"
        ]
    return projected


def _connection_status(connection: object) -> str | None:
    if not isinstance(connection, Mapping):
        return None
    properties = connection.get("properties")
    if not isinstance(properties, Mapping):
        return None
    state = properties.get("privateLinkServiceConnectionState")
    if not isinstance(state, Mapping) or not isinstance(state.get("status"), str):
        return None
    return str(state["status"]).casefold()


def _secret_store(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = _properties(row)
    if properties is None:
        return {}
    projected: dict[str, Any] = {}
    _set_bool(projected, "rbac_authorization_enabled", properties.get("enableRbacAuthorization"))
    _set_bool(projected, "soft_delete_enabled", properties.get("enableSoftDelete"))
    _public_network_access(projected, properties.get("publicNetworkAccess"))
    purge = properties.get("enablePurgeProtection")
    if isinstance(purge, bool):
        projected["purge_protection_enabled"] = purge
    elif purge is None:
        # ARM documents that this property never accepts false: absent means not enabled.
        projected["purge_protection_enabled"] = False
    return projected


def _network_security_group(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = _properties(row)
    if properties is None:
        return {}
    rules = properties.get("securityRules")
    if not isinstance(rules, Sequence) or isinstance(rules, str) or len(rules) > MAX_SECURITY_RULES:
        return {}
    projected_rules: list[dict[str, Any]] = []
    complete_rules: list[dict[str, Any]] = []
    for rule in rules:
        rule_properties_value = rule.get("properties") if isinstance(rule, Mapping) else None
        if not isinstance(rule_properties_value, Mapping):
            # One unreadable rule makes the whole set unobserved instead of partially clean.
            return {}
        projected_rules.append(_security_rule(rule_properties_value))
        complete = _security_rule(rule_properties_value, scope_fields=True)
        priority = _priority(rule)
        if priority is not None:
            complete["priority"] = priority
        if str(complete.get("direction", "")).casefold() == "inbound":
            complete_rules.append(complete)
    # The complete inbound set, with wildcards, ranges, lists, scope fields, and priorities, for
    # Rules that judge every shape (network.nsg.no-internet-inbound-*).
    projected: dict[str, Any] = {"inbound_security_rules": complete_rules}
    # The exact-literal Rules (network.nsg.no-inbound-any-*) can't judge an alias, wildcard,
    # range, or list, so their property stays unobserved instead of looking clean.
    if all(_decidable_inbound_allow(item) for item in projected_rules):
        projected["security_rules"] = projected_rules
    return projected


def _security_rule(
    rule_properties_value: Mapping[str, Any],
    *,
    scope_fields: bool = False,
) -> dict[str, Any]:
    projected_rule: dict[str, Any] = {}
    for source, target in (
        ("direction", "direction"),
        ("access", "access"),
        ("protocol", "protocol"),
        ("destinationPortRange", "destination_port_range"),
        ("sourceAddressPrefix", "source_address_prefix"),
    ):
        _set_text(projected_rule, target, rule_properties_value.get(source))
    for source, target in (
        ("destinationPortRanges", "destination_port_ranges"),
        ("sourceAddressPrefixes", "source_address_prefixes"),
    ):
        value = rule_properties_value.get(source)
        if isinstance(value, Sequence) and not isinstance(value, str):
            projected_rule[target] = [str(item) for item in value]
    if scope_fields:
        # A deny scoped to some destinations or source ports blocks only part of the traffic, so
        # the complete set carries those fields for the Rules to tell a full block from a partial.
        for source, target in (
            ("destinationAddressPrefix", "destination_address_prefix"),
            ("sourcePortRange", "source_port_range"),
        ):
            _set_text(projected_rule, target, rule_properties_value.get(source))
        for source, target in (
            ("destinationAddressPrefixes", "destination_address_prefixes"),
            ("sourcePortRanges", "source_port_ranges"),
        ):
            value = rule_properties_value.get(source)
            if isinstance(value, Sequence) and not isinstance(value, str):
                projected_rule[target] = [str(item) for item in value]
        groups = rule_properties_value.get("destinationApplicationSecurityGroups")
        if isinstance(groups, Sequence) and not isinstance(groups, str) and groups:
            projected_rule["destination_application_security_groups"] = len(groups)
    return projected_rule


def _priority(rule: Any) -> int | None:
    rule_properties_value = rule.get("properties") if isinstance(rule, Mapping) else None
    priority = (
        rule_properties_value.get("priority")
        if isinstance(rule_properties_value, Mapping)
        else None
    )
    return priority if isinstance(priority, int) and not isinstance(priority, bool) else None


def _decidable_inbound_allow(rule: Mapping[str, Any]) -> bool:
    """Whether an inbound allow rule uses only values the exact-literal NSG Rules can judge."""

    if str(rule.get("direction", "")).casefold() != "inbound":
        return True
    if str(rule.get("access", "")).casefold() != "allow":
        return True
    if "destination_port_ranges" in rule or "source_address_prefixes" in rule:
        return False
    protocol = rule.get("protocol")
    port = rule.get("destination_port_range")
    source = rule.get("source_address_prefix")
    return (
        isinstance(protocol, str)
        and protocol != "*"
        and isinstance(port, str)
        and port.isdigit()
        and isinstance(source, str)
        and source.casefold() not in _ANY_SOURCE_ALIASES
    )


def _postgresql_server(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = _properties(row)
    if properties is None:
        return {}
    projected: dict[str, Any] = {}
    high_availability = properties.get("highAvailability")
    if isinstance(high_availability, Mapping):
        _set_text(projected, "ha_mode", high_availability.get("mode"))
    data_encryption = properties.get("dataEncryption")
    if isinstance(data_encryption, Mapping) and isinstance(data_encryption.get("type"), str):
        # Service-managed or customer-managed keys both encrypt data at rest.
        projected["encryption_at_rest_enabled"] = str(data_encryption["type"]).casefold() in {
            "systemmanaged",
            "azurekeyvault",
        }
    ssl = properties.get("sslEnforcement")
    if isinstance(ssl, str) and ssl.strip():
        projected["ssl_enforcement"] = ssl.strip().casefold()
    return projected


def _sql_database(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = _properties(row)
    projected: dict[str, Any] = {}
    if properties is not None:
        _set_bool(projected, "zone_redundant", properties.get("zoneRedundant"))
    return projected


def _kubernetes_cluster(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = _properties(row)
    if properties is None:
        return {}
    projected: dict[str, Any] = {}
    network = properties.get("networkProfile")
    if isinstance(network, Mapping):
        policy = network.get("networkPolicy")
        if policy is None:
            projected["network_policy"] = False
        elif isinstance(policy, str):
            projected["network_policy"] = policy.strip().casefold() not in {"", "none"}
    aad = properties.get("aadProfile")
    if isinstance(aad, Mapping):
        _set_bool(projected, "azure_rbac_enabled", aad.get("enableAzureRBAC"))
    api_server = properties.get("apiServerAccessProfile")
    if isinstance(api_server, Mapping):
        _set_bool(projected, "private_cluster_enabled", api_server.get("enablePrivateCluster"))
    return projected


def _kubernetes_node_pool(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = _properties(row)
    if properties is None:
        return {}
    if "availabilityZones" not in properties:
        # Node pools come from the complete ARM agentPools response, which omits the field for a
        # pool without zones; absence there is the documented "no zones" state.
        return {"availability_zones": []}
    zones = properties.get("availabilityZones")
    if isinstance(zones, Sequence) and not isinstance(zones, str):
        if all(isinstance(item, str) for item in zones):
            return {"availability_zones": sorted(zones)}
    return {}


def _compute_vm(row: Mapping[str, Any]) -> dict[str, Any]:
    if "identity" not in row:
        return {}
    identity = row["identity"]
    if identity is None:
        return {"identity_type": "None"}
    if isinstance(identity, Mapping) and isinstance(identity.get("type"), str):
        return {"identity_type": str(identity["type"]).strip() or "None"}
    return {}


def _zoned(key: str) -> _Projector:
    def project(row: Mapping[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        _zones(projected, row, key)
        return projected

    return project


_PROJECTORS: Mapping[str, _Projector] = {
    "cache": _zoned("zones"),
    "compute.vm": _compute_vm,
    "compute.vm-scale-set": _zoned("zones"),
    "kubernetes-cluster": _kubernetes_cluster,
    "kubernetes-node-pool": _kubernetes_node_pool,
    "network.nsg": _network_security_group,
    "object-storage": _object_storage,
    "postgresql-server": _postgresql_server,
    "secret-store": _secret_store,
    "sql-database": _sql_database,
}


__all__ = ["MAX_PROJECTED_BYTES", "MAX_SECURITY_RULES", "rule_properties"]
