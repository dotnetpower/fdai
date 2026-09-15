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
                "private_cluster_enabled": "true",
                "local_account_disabled": "true",
                "role_based_access_control_enabled": "true",
                "automatic_upgrade_channel": '"patch"',
                "node_os_upgrade_channel": '"NodeImage"',
                "host_encryption_enabled": "true",
                "os_disk_type": '"Managed"',
                "max_pods": "50",
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
