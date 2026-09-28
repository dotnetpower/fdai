"""Select bounded Terraform targets for standalone deployment stages."""

from __future__ import annotations

from typing import Final

_SUBSTRATE_TARGETS: Final = (
    "module.resource_group",
    "module.log_analytics",
    "azurerm_application_insights.core",
    "module.network",
    "module.container_registry",
    "module.acr_private_endpoint",
    "azurerm_role_assignment.deploy_runner_acr_push",
    "module.identity",
    "module.identity_change",
    "module.identity_resilience",
    "module.identity_finops",
    "module.command_api_identity",
    "module.inventory_identity",
    "module.canary_identity",
    "module.operator_api_identity",
    "module.isolated_executor_identity",
    "module.ingestion_identity",
    "module.ingestion_worker_identity",
    "module.key_vault",
    "azurerm_role_assignment.kv_officer_self",
    "module.kv_private_endpoint",
    "module.state_store",
    "module.postgres_public_mode_private_endpoint",
    "module.event_bus",
    "module.event_bus_auxiliary",
    "module.event_bus_private_endpoint",
    "azurerm_key_vault_secret.state_store_dsn",
    "azurerm_key_vault_secret.application_insights_connection_string",
    "azurerm_role_assignment.core_application_insights_secret_reader",
    "azurerm_key_vault_secret.github_app_private_key",
    "azurerm_role_assignment.core_github_app_private_key_reader",
    "azurerm_role_assignment.command_api_eventhubs_sender",
    "azurerm_role_assignment.command_api_eventhubs_receiver",
    "azurerm_role_assignment.inventory_reader",
    "azurerm_role_assignment.inventory_monitoring_reader",
    "azurerm_role_assignment.inventory_log_analytics_reader",
    "azurerm_role_assignment.inventory_cost_reader",
    "azurerm_role_assignment.inventory_kubernetes_reader",
    "azurerm_role_assignment.inventory_eventhubs_sender",
    "azurerm_role_assignment.inventory_stage_sender",
    "azurerm_role_assignment.inventory_eventhubs_raw_sender",
    "azurerm_role_assignment.canary_eventhubs_sender",
    "azurerm_role_assignment.inventory_kv_secrets_user",
    "azurerm_role_assignment.operator_api_kv_secrets_user",
    "azurerm_role_assignment.isolated_executor_kv_secrets_user",
    "module.document_storage",
    "module.document_blob_private_endpoint",
    "module.document_dfs_private_endpoint",
    "azurerm_private_dns_a_record.document_blob_ops",
    "azurerm_role_assignment.ingestion_document_data",
    "azurerm_role_assignment.ingestion_worker_document_data",
    "azurerm_key_vault_secret.ingestion_api_dsn",
    "azurerm_key_vault_secret.ingestion_worker_dsn",
    "azurerm_role_assignment.ingestion_api_kv_secrets_user",
    "azurerm_role_assignment.ingestion_worker_kv_secrets_user",
    "azurerm_role_assignment.ingestion_aks_eventhubs_sender",
    "azurerm_role_assignment.ingestion_worker_aks_eventhubs_receiver",
    "azurerm_role_assignment.ingestion_worker_eventhubs_sender",
    "azurerm_role_assignment.ingestion_worker_pantheon_receiver",
    "azurerm_role_assignment.executor_eventhubs_data_owner",
    "module.console",
    "module.operational_history_storage",
    "random_id.cost_pseudonym_key",
    "azurerm_key_vault_secret.cost_pseudonym_key",
    "azurerm_role_assignment.operator_cost_pseudonym_secret_reader",
)


def database_placement(context: dict[str, object]) -> str:
    value = context.get("runtime_profile")
    if value is None:
        return "postgres-flex"
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("runtime deployment profile is invalid")
    placement = value.get("database_placement")
    if placement not in {"postgres-flex", "postgres-aks"}:
        raise ValueError("database placement is invalid")
    return str(placement)


def stage_targets(stage: str, context: dict[str, object]) -> tuple[str, ...]:
    if stage == "access":
        return focused_access_targets(context)
    if stage == "substrate":
        return substrate_targets(context)
    return ()


def focused_private_access(context: dict[str, object]) -> bool:
    key_vault = context.get("key_vault_private_access")
    document_storage = context.get("document_storage_private_access")
    if type(key_vault) is not bool or type(document_storage) is not bool:
        raise ValueError("focused private-access context is invalid")
    return key_vault or document_storage


def focused_access_targets(context: dict[str, object]) -> tuple[str, ...]:
    if not focused_private_access(context):
        raise ValueError("focused private-access plan was not selected")
    targets: list[str] = []
    if context["key_vault_private_access"] is True:
        targets.extend(
            (
                "module.kv_private_endpoint",
                "azurerm_role_assignment.kv_officer_self",
            )
        )
    if context["document_storage_private_access"] is True:
        targets.extend(
            (
                "module.document_blob_private_endpoint",
                "module.document_dfs_private_endpoint",
                "module.document_storage[0].azurerm_role_assignment.deployer_data_owner",
                "azurerm_private_dns_a_record.document_blob_ops",
            )
        )
    targets.extend(
        (
            "azurerm_virtual_network_peering.spoke_to_hub",
            "azurerm_virtual_network_peering.hub_to_spoke",
        )
    )
    return tuple(targets)


def substrate_targets(context: dict[str, object]) -> tuple[str, ...]:
    if database_placement(context) == "postgres-flex":
        return _SUBSTRATE_TARGETS
    excluded = {
        "module.state_store",
        "module.postgres_public_mode_private_endpoint",
        "azurerm_key_vault_secret.state_store_dsn",
        "azurerm_role_assignment.inventory_kv_secrets_user",
        "azurerm_role_assignment.operator_api_kv_secrets_user",
        "azurerm_role_assignment.isolated_executor_kv_secrets_user",
    }
    return tuple(target for target in _SUBSTRATE_TARGETS if target not in excluded)
