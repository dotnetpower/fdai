mock_provider "azurerm" {}

override_data {
  target = data.azurerm_client_config.current
  values = {
    subscription_id = "00000000-0000-0000-0000-000000000000"
    tenant_id       = "00000000-0000-0000-0000-000000000000"
    object_id       = "00000000-0000-0000-0000-000000000001"
  }
}

override_data {
  target = data.azurerm_resource_group.target
  values = {
    id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3"
    name     = "rg-fdai-dev-wus3"
    location = "westus3"
  }
}

override_data {
  target = data.azurerm_container_registry.target
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.ContainerRegistry/registries/crfdaidevwus3example"
    login_server = "crfdaidevwus3example.azurecr.io"
  }
}

override_data {
  target = data.azurerm_key_vault.target
  values = {
    id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.KeyVault/vaults/kv-fdai-dev-wus3"
    vault_uri = "https://kv-fdai-dev-wus3.vault.azure.net/"
  }
}

override_data {
  target = data.azurerm_key_vault_secret.state_store_dsn
  values = {
    id                      = "https://kv-fdai-dev-wus3.vault.azure.net/secrets/fdai-state-store-dsn/version"
    resource_versionless_id = "https://kv-fdai-dev-wus3.vault.azure.net/secrets/fdai-state-store-dsn"
    value                   = "postgresql://example.invalid/fdai?sslmode=require"
  }
}

override_data {
  target = data.azurerm_eventhub.pantheon_objects
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.EventHub/namespaces/evhns-fdai-dev-wus3/eventhubs/fdai.pantheon.objects"
  }
}

override_data {
  target = data.azurerm_eventhub.pipeline_stages
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.EventHub/namespaces/evhns-fdai-dev-wus3/eventhubs/fdai.pipeline.stages"
  }
}

override_data {
  target = data.azurerm_log_analytics_workspace.target
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.OperationalInsights/workspaces/log-fdai-dev-wus3"
  }
}

override_data {
  target = data.azurerm_virtual_network.target
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.Network/virtualNetworks/vnet-fdai-dev-wus3"
  }
}

override_data {
  target = data.azurerm_virtual_network.ops
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-ops-wus3/providers/Microsoft.Network/virtualNetworks/vnet-fdai-ops-wus3"
  }
}

override_data {
  target = data.azurerm_private_dns_zone.ops_blob
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-ops-wus3/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
  }
}

override_data {
  target = data.azurerm_subnet.private_endpoints
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.Network/virtualNetworks/vnet-fdai-dev-wus3/subnets/snet-pe"
  }
}

override_data {
  target = data.azurerm_kubernetes_cluster.target
  values = {
    id              = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-wus3/providers/Microsoft.ContainerService/managedClusters/aks-fdai-dev-wus3"
    oidc_issuer_url = "https://oidc.example.invalid/"
  }
}

variables {
  location                     = "westus3"
  resource_group_name          = "rg-fdai-dev-wus3"
  acr_name                     = "crfdaidevwus3example"
  key_vault_name               = "kv-fdai-dev-wus3"
  eventhub_namespace_name      = "evhns-fdai-dev-wus3"
  log_analytics_workspace_name = "log-fdai-dev-wus3"
  vnet_name                    = "vnet-fdai-dev-wus3"
  ops_resource_group_name      = "rg-fdai-ops-wus3"
  ops_vnet_name                = "vnet-fdai-ops-wus3"
  aks_name                     = "aks-fdai-dev-wus3"
  name_suffix                  = "abc123"
  document_storage_name        = "stfdaidocwus3abc123"
  deployer_principal_id        = "00000000-0000-0000-0000-000000000002"
}

run "plans_only_stewardship_prerequisites" {
  command = plan

  assert {
    condition = (
      length(module.identity) == 4 &&
      length(azurerm_federated_identity_credential.workload) == 4 &&
      length(azurerm_role_assignment.acr_pull) == 3 &&
      length(azurerm_role_assignment.document_data) == 2 &&
      output.evidence.workload_container_app_count == 0 &&
      output.evidence.workload_container_job_count == 0
    )
    error_message = "The Hub prerequisite root must retain four identities and no application workload resources."
  }

  assert {
    condition = (
      azurerm_role_assignment.api_secret_reader.role_definition_name == "Key Vault Secrets User" &&
      azurerm_role_assignment.worker_secret_reader.role_definition_name == "Key Vault Secrets User" &&
      azurerm_role_assignment.migration_secret_reader.role_definition_name == "Key Vault Secrets User" &&
      azurerm_role_assignment.notification_sender.role_definition_name == "Communication and Email Service Owner"
    )
    error_message = "The Hub prerequisite root must retain the reviewed secret and notification role ceilings."
  }

  assert {
    condition = (
      length(module.document_blob_private_endpoint.private_dns_zone_ids) == 2 &&
      contains(
        module.document_blob_private_endpoint.private_dns_zone_ids,
        data.azurerm_private_dns_zone.ops_blob.id,
      )
    )
    error_message = "The document Blob endpoint must publish its record to the existing operations Blob private DNS zone."
  }
}
