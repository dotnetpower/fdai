"""Static guardrails for the two-Hub development data planes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "infra/hubs-development"


def _resource(path: str, kind: str, name: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(rf'resource "{kind}" "{name}" \{{(.*?)\n\}}', source, re.S)
    assert match is not None, f"Missing {kind}.{name} in {path}"
    return match.group(1)


def test_vault_disables_public_access_and_denies_network_fallback() -> None:
    vault = _resource("boundaries.tf", "azurerm_key_vault", "hub")
    assert re.search(r"for_each\s*=\s*local\.kinds", vault)
    assert re.search(r"public_network_access_enabled\s*=\s*false", vault)
    acl = re.search(r"network_acls \{([^}]+)\}", vault)
    assert acl is not None
    assert re.search(r'default_action\s*=\s*"Deny"', acl.group(1))
    assert re.search(r'bypass\s*=\s*"None"', acl.group(1))
    assert not re.search(r"\b(?:ip_rules|virtual_network_subnet_ids)\s*=", acl.group(1))


def test_each_vault_retains_its_own_private_endpoint_and_dns() -> None:
    endpoint = _resource("boundaries.tf", "azurerm_private_endpoint", "vault")
    assert re.search(r"for_each\s*=\s*local\.kinds", endpoint)
    assert re.search(r"subnet_id\s*=\s*azurerm_subnet\.secrets\[each\.key\]\.id", endpoint)
    assert re.search(
        r"private_connection_resource_id\s*=\s*azurerm_key_vault\.hub\[each\.key\]\.id", endpoint
    )
    assert re.search(r'subresource_names\s*=\s*\["vault"\]', endpoint)
    assert re.search(
        r"private_dns_zone_ids\s*=\s*\[azurerm_private_dns_zone\.vault\[each\.key\]\.id\]",
        endpoint,
    )


@pytest.mark.parametrize("name", ["apps", "database", "secrets"])
def test_managed_subnets_disable_implicit_outbound_access(name: str) -> None:
    subnet = _resource("boundaries.tf", "azurerm_subnet", name)
    assert re.search(r"for_each\s*=\s*local\.kinds", subnet)
    assert re.search(r"default_outbound_access_enabled\s*=\s*false", subnet)
    if name == "secrets":
        assert re.search(r'private_endpoint_network_policies\s*=\s*"Disabled"', subnet)
    else:
        service = (
            "Microsoft.App/environments"
            if name == "apps"
            else "Microsoft.DBforPostgreSQL/flexibleServers"
        )
        assert f'"{service}"' in subnet


def test_development_backup_policy_remains_explicit() -> None:
    server = _resource("boundaries.tf", "azurerm_postgresql_flexible_server", "hub")
    assert re.search(r"backup_retention_days\s*=\s*7\b", server)
    assert re.search(r"geo_redundant_backup_enabled\s*=\s*false", server)
    assert re.search(r"public_network_access_enabled\s*=\s*false", server)


@pytest.mark.parametrize(
    ("resource_name", "parameter", "value"),
    [
        ("log_connections", "log_connections", "on"),
        ("log_checkpoints", "log_checkpoints", "on"),
        ("connection_throttle", "connection_throttle.enable", "on"),
        ("tls_floor", "ssl_min_protocol_version", "TLSv1.2"),
    ],
)
def test_both_databases_declare_security_parameters(
    resource_name: str, parameter: str, value: str
) -> None:
    block = _resource(
        "boundaries.tf", "azurerm_postgresql_flexible_server_configuration", resource_name
    )
    assert re.search(r"for_each\s*=\s*local\.kinds", block)
    assert re.search(rf'name\s*=\s*"{re.escape(parameter)}"', block)
    assert re.search(rf'value\s*=\s*"{re.escape(value)}"', block)
    assert re.search(
        r"server_id\s*=\s*azurerm_postgresql_flexible_server\.hub\[each\.key\]\.id", block
    )


@pytest.mark.parametrize(
    ("path", "kind", "name"),
    [
        ("apps.tf", "azurerm_container_app", "hub"),
        ("migrations.tf", "azurerm_container_app_job", "migrate"),
    ],
)
def test_workloads_wait_for_database_security_parameters(path: str, kind: str, name: str) -> None:
    block = _resource(path, kind, name)
    dependencies = re.search(r"depends_on\s*=\s*\[([^]]+)\]", block)
    assert dependencies is not None
    for name in ("log_connections", "log_checkpoints", "connection_throttle", "tls_floor"):
        assert f"azurerm_postgresql_flexible_server_configuration.{name}" in dependencies.group(1)
