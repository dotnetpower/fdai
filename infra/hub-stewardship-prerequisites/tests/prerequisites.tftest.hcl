mock_provider "azurerm" {}
mock_provider "kubernetes" {}

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
    id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example"
    name     = "rg-fdai-example"
    location = "westus3"
  }
}

override_data {
  target = data.azurerm_container_registry.target
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.ContainerRegistry/registries/acmefdai"
    login_server = "acmefdai.azurecr.io"
  }
}

override_data {
  target = data.azurerm_key_vault.target
  values = {
    id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.KeyVault/vaults/kv-fdai-example"
    name      = "kv-fdai-example"
    vault_uri = "https://kv-fdai-example.vault.azure.net/"
  }
}

override_data {
  target = data.azurerm_key_vault_secret.state_store_dsn
  values = {
    id                      = "https://kv-fdai-example.vault.azure.net/secrets/fdai-state-store-dsn/version"
    resource_versionless_id = "https://kv-fdai-example.vault.azure.net/secrets/fdai-state-store-dsn"
    value                   = "postgresql://example.invalid/fdai?sslmode=require"
  }
}

override_data {
  target = data.azurerm_eventhub.pantheon_objects
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.EventHub/namespaces/evhns-fdai-example/eventhubs/fdai.pantheon.objects"
  }
}

override_data {
  target = data.azurerm_eventhub.pipeline_stages
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.EventHub/namespaces/evhns-fdai-example/eventhubs/fdai.pipeline.stages"
  }
}

override_data {
  target = data.azurerm_log_analytics_workspace.target
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.OperationalInsights/workspaces/log-fdai-example"
  }
}

override_data {
  target = data.azurerm_virtual_network.target
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.Network/virtualNetworks/vnet-fdai-example"
  }
}

override_data {
  target = data.azurerm_virtual_network.ops
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-ops-example/providers/Microsoft.Network/virtualNetworks/vnet-fdai-ops-example"
  }
}

override_data {
  target = data.azurerm_private_dns_zone.ops_blob
  values = {
    id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-ops-example/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    name                = "privatelink.blob.core.windows.net"
    resource_group_name = "rg-fdai-ops-example"
  }
}

override_data {
  target = data.azurerm_subnet.private_endpoints
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.Network/virtualNetworks/vnet-fdai-example/subnets/snet-pe"
  }
}

override_data {
  target = data.azurerm_kubernetes_cluster.target
  values = {
    id              = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-example/providers/Microsoft.ContainerService/managedClusters/aks-fdai-example"
    oidc_issuer_url = "https://oidc.example.invalid/"
  }
}

variables {
  location                     = "westus3"
  resource_group_name          = "rg-fdai-example"
  acr_name                     = "acmefdai"
  key_vault_name               = "kv-fdai-example"
  eventhub_namespace_name      = "evhns-fdai-example"
  log_analytics_workspace_name = "log-fdai-example"
  vnet_name                    = "vnet-fdai-example"
  ops_resource_group_name      = "rg-fdai-ops-example"
  ops_vnet_name                = "vnet-fdai-ops-example"
  aks_name                     = "aks-fdai-example"
  kubeconfig_path              = "/unused/mock-kubeconfig"
  kubeconfig_context           = "example"
  tenant_id                    = "00000000-0000-0000-0000-000000000000"
  identity_names = {
    ingestion    = "id-fdai-example-ingestion"
    worker       = "id-fdai-example-worker"
    migration    = "id-fdai-example-migration"
    notification = "id-fdai-example-notification"
    operator_api = "id-fdai-example-operator-api"
    command      = "id-fdai-example-command"
  }
  document_storage_name                       = "acmefdaidocuments"
  document_intelligence_name                  = "di-fdai-example"
  document_blob_private_endpoint_name         = "pe-fdai-example-blob"
  document_dfs_private_endpoint_name          = "pe-fdai-example-dfs"
  document_intelligence_private_endpoint_name = "pe-fdai-example-di"
  communication_service_name                  = "acs-fdai-example"
  email_communication_service_name            = "ec-fdai-example"
  deployer_principal_id                       = "00000000-0000-0000-0000-000000000002"
  config_map_data = {
    analyzer-job-env               = { FDAI_COMPONENT = "analyzer" }
    canary-job-env                 = { FDAI_COMPONENT = "canary" }
    core-control-plane-env         = { FDAI_COMPONENT = "core-control-plane" }
    document-ingestion-api-env     = { FDAI_COMPONENT = "document-ingestion-api" }
    document-processing-worker-env = { FDAI_COMPONENT = "document-processing-worker" }
    inventory-job-env              = { FDAI_COMPONENT = "inventory" }
    observation-campaign-job-env   = { FDAI_COMPONENT = "observation-campaign" }
    operator-service-env           = { FDAI_COMPONENT = "operator-service" }
  }
  secret_bindings = {
    document-ingestion-api = {
      FDAI_DATABASE_URL = "fdai-ingestion-api-dsn"
    }
    document-processing-worker = {
      FDAI_DATABASE_URL = "fdai-ingestion-worker-dsn"
    }
    operator-service = {
      FDAI_COST_PSEUDONYM_KEY                     = "fdai-cost-pseudonym-key"
      FDAI_DATABASE_URL                           = "fdai-state-store-dsn"
      FDAI_OPERATOR_REQUEST_OPERATOR_SIGNING_SEED = "fdai-operator-request-operator-signing-seed"
    }
  }
}

run "plans_only_stewardship_prerequisites" {
  command = plan

  assert {
    condition = (
      length(module.identity) == 6 &&
      length(azurerm_federated_identity_credential.workload) == 6 &&
      length(azurerm_role_assignment.acr_pull) == 3 &&
      length(azurerm_role_assignment.document_data) == 2 &&
      length(kubernetes_service_account_v1.prerequisite) == 4 &&
      length(kubernetes_config_map_v1.runtime_environment) == 8 &&
      length(kubernetes_manifest.secret_provider) == 3 &&
      length(kubernetes_secret_v1.runtime) == 3 &&
      output.evidence.workload_deployment_count == 0 &&
      output.evidence.workload_service_count == 0 &&
      output.evidence.workload_horizontal_pod_autoscaler_count == 0 &&
      output.evidence.workload_cron_job_count == 0 &&
      output.evidence.workload_container_app_count == 0 &&
      output.evidence.workload_container_job_count == 0
    )
    error_message = "The Hub prerequisite root must retain six identities, the exact Kubernetes prerequisites, and no application workload resources."
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
      azurerm_private_dns_a_record.document_blob_ops.zone_name == data.azurerm_private_dns_zone.ops_blob.name &&
      azurerm_private_dns_a_record.document_blob_ops.resource_group_name == var.ops_resource_group_name &&
      length(azurerm_private_dns_a_record.document_blob_ops.records) == 1
    )
    error_message = "The document Blob endpoint must publish its record to the existing operations Blob private DNS zone."
  }

  assert {
    condition = (
      azurerm_federated_identity_credential.workload["operator_api"].subject == "system:serviceaccount:fdai-runtime:operator-service" &&
      azurerm_federated_identity_credential.workload["command"].subject == "system:serviceaccount:fdai-runtime:operator-service" &&
      contains(keys(kubernetes_service_account_v1.prerequisite["operator-service"].metadata[0].annotations), "azure.workload.identity/client-id") &&
      toset(keys(output.topology_generation.identity_bindings)) == toset([
        "document-ingestion-api",
        "document-processing-worker",
        "operator-service",
      ]) &&
      toset(keys(output.topology_generation.identity_bindings["operator-service"].additional_identities)) == toset(["command"]) &&
      output.topology_generation.migration_identity_binding.service_account == "fdai-schema-migration"
    )
    error_message = "Operator API and command identities must remain separately bound to the operator-service ServiceAccount."
  }

  assert {
    condition = (
      toset(output.retained_ownership.kubernetes.service_accounts) == toset([
        "document-ingestion-api",
        "document-processing-worker",
        "fdai-schema-migration",
        "operator-service",
      ]) &&
      toset(output.retained_ownership.kubernetes.secret_provider_classes) == toset([
        "document-ingestion-api",
        "document-processing-worker",
        "operator-service",
      ]) &&
      toset(output.retained_ownership.kubernetes.secrets) == toset([
        "document-ingestion-api",
        "document-processing-worker",
        "operator-service",
      ]) &&
      toset(output.retained_ownership.lifecycle_agent_managed_kinds) == toset([
        "CronJob",
        "Deployment",
        "HorizontalPodAutoscaler",
        "Service",
      ])
    )
    error_message = "The retained ownership contract must keep prerequisites in Terraform and managed workloads with the Lifecycle Agent."
  }

  assert {
    condition = (
      kubernetes_manifest.secret_provider["operator-service"].manifest.spec.secretObjects[0].secretName == "operator-service" &&
      length(kubernetes_manifest.secret_provider["operator-service"].manifest.spec.secretObjects[0].data) == 3
    )
    error_message = "The Operator SecretProviderClass must retain all exact generated Kubernetes Secret bindings."
  }
}

run "rejects_incomplete_config_map_inventory" {
  command = plan

  variables {
    config_map_data = {
      analyzer-job-env = { FDAI_COMPONENT = "analyzer" }
    }
  }

  expect_failures = [var.config_map_data]
}

run "rejects_incomplete_secret_binding_inventory" {
  command = plan

  variables {
    secret_bindings = {
      operator-service = {
        FDAI_DATABASE_URL = "fdai-state-store-dsn"
      }
    }
  }

  expect_failures = [var.secret_bindings]
}
