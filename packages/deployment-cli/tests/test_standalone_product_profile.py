"""Standalone Terraform values for observation-first and explicit add-ons."""

from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.standalone_product_profile import product_terraform_values


def test_observation_first_values_construct_no_add_on_binding() -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
    )

    values = product_terraform_values(
        profile,
        {},
        require_guid=lambda *_args: (_ for _ in ()).throw(
            AssertionError("default profile read enterprise identity")
        ),
    )

    assert values["enable_console"] is False
    assert values["enable_operator_api"] is False
    assert values["enable_isolated_executor"] is False
    assert values["enable_governed_execution"] is False
    assert values["enable_email_notifications"] is False
    assert values["enable_document_ingestion"] is False
    assert values["enable_inventory_monitoring_reader"] is False
    assert values["enable_inventory_log_analytics_reader"] is False
    assert values["enable_inventory_cost_management_reader"] is False
    assert values["enable_inventory_aks_reader"] is False
    assert values["enable_inventory_evidence_store_reader"] is False
    assert not any(key.startswith("rbac_") for key in values)
    rendered = json.dumps(values, sort_keys=True)
    assert "tenant_id" not in rendered
    assert "secret" not in rendered


def test_explicit_full_product_values_preserve_existing_surfaces() -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
        product_add_ons=(
            "enterprise-identity-governance",
            "governed-execution",
            "notifications",
            "read-only-console",
        ),
        observation_data_sources=(
            "aks",
            "azure-monitor",
            "cost-management",
            "evidence-store",
            "log-analytics",
        ),
    )
    entra = {
        "CURRENT_OPERATOR_OBJECT_ID": "operator",
        "OPERATOR_API_AUDIENCE": "audience",
        "RBAC_READERS_GROUP_ID": "reader",
        "RBAC_CONTRIBUTORS_GROUP_ID": "contributor",
        "RBAC_APPROVERS_GROUP_ID": "approver",
        "RBAC_OWNERS_GROUP_ID": "owner",
        "RBAC_BREAK_GLASS_GROUP_ID": "break-glass",
    }

    values = product_terraform_values(
        profile,
        entra,
        require_guid=lambda source, key: str(source[key]),
    )

    assert values["enable_console"] is True
    assert values["enable_operator_api"] is True
    assert values["enable_isolated_executor"] is True
    assert values["enable_governed_execution"] is True
    assert values["enable_email_notifications"] is True
    assert values["enable_inventory_monitoring_reader"] is True
    assert values["enable_inventory_log_analytics_reader"] is True
    assert values["enable_inventory_cost_management_reader"] is True
    assert values["enable_inventory_aks_reader"] is True
    assert values["enable_inventory_evidence_store_reader"] is True
    assert values["operator_api_audience"] == "audience"
    assert values["rbac_owners_group_id"] == "owner"


@pytest.mark.parametrize(
    ("source", "selected_key"),
    [
        ("aks", "enable_inventory_aks_reader"),
        ("azure-monitor", "enable_inventory_monitoring_reader"),
        ("cost-management", "enable_inventory_cost_management_reader"),
        ("evidence-store", "enable_inventory_evidence_store_reader"),
        ("log-analytics", "enable_inventory_log_analytics_reader"),
    ],
)
def test_each_data_source_derives_only_its_own_read_role(
    source: str,
    selected_key: str,
) -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
        observation_data_sources=(source,),
    )

    values = product_terraform_values(
        profile,
        {},
        require_guid=lambda *_args: "unused",
    )
    role_keys = {
        "enable_inventory_aks_reader",
        "enable_inventory_monitoring_reader",
        "enable_inventory_cost_management_reader",
        "enable_inventory_evidence_store_reader",
        "enable_inventory_log_analytics_reader",
    }

    assert values[selected_key] is True
    assert all(values[key] is False for key in role_keys - {selected_key})
