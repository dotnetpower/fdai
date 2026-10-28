locals {
  service_account_identities = {
    document-ingestion-api     = "ingestion"
    document-processing-worker = "worker"
    fdai-schema-migration      = "migration"
    operator-service           = "operator_api"
  }
  secret_binding_identities = {
    document-ingestion-api     = "ingestion"
    document-processing-worker = "worker"
    operator-service           = "operator_api"
  }
  runtime_secret_names = toset(flatten([
    for bindings in values(var.secret_bindings) : values(bindings)
  ]))
  existing_runtime_secret_names = setsubtract(local.runtime_secret_names, toset([
    "fdai-ingestion-api-dsn",
    "fdai-ingestion-worker-dsn",
  ]))
  runtime_secret_values = merge(
    {
      "fdai-ingestion-api-dsn"    = azurerm_key_vault_secret.ingestion_api_dsn.value
      "fdai-ingestion-worker-dsn" = azurerm_key_vault_secret.ingestion_worker_dsn.value
    },
    {
      for name, secret in data.azurerm_key_vault_secret.runtime : name => secret.value
    },
  )
}

data "azurerm_key_vault_secret" "runtime" {
  for_each = local.existing_runtime_secret_names

  name         = each.key
  key_vault_id = data.azurerm_key_vault.target.id
}

resource "kubernetes_service_account_v1" "prerequisite" {
  for_each = local.service_account_identities

  metadata {
    name      = each.key
    namespace = var.namespace
    annotations = {
      "azure.workload.identity/client-id" = module.identity[each.value].client_id
      "azure.workload.identity/tenant-id" = var.tenant_id
    }
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
      "app.kubernetes.io/part-of"    = "fdai"
    }
  }
}

resource "kubernetes_config_map_v1" "runtime_environment" {
  for_each = var.config_map_data

  metadata {
    name      = each.key
    namespace = var.namespace
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
      "app.kubernetes.io/part-of"    = "fdai"
    }
  }

  data = each.value
}

resource "kubernetes_manifest" "secret_provider" {
  for_each = var.secret_bindings

  manifest = {
    apiVersion = "secrets-store.csi.x-k8s.io/v1"
    kind       = "SecretProviderClass"
    metadata = {
      name      = each.key
      namespace = var.namespace
      labels = {
        "app.kubernetes.io/managed-by" = "terraform"
        "app.kubernetes.io/part-of"    = "fdai"
      }
    }

    spec = {
      provider = "azure"
      parameters = {
        usePodIdentity = "false"
        clientID       = module.identity[local.secret_binding_identities[each.key]].client_id
        keyvaultName   = data.azurerm_key_vault.target.name
        tenantId       = var.tenant_id
        objects = yamlencode({
          array = [
            for object_name in sort(distinct(values(each.value))) :
            yamlencode({
              objectName = object_name
              objectType = "secret"
            })
          ]
        })
      }
      secretObjects = [{
        secretName = each.key
        type       = "Opaque"
        data = [
          for environment_name, object_name in each.value : {
            key        = environment_name
            objectName = object_name
          }
        ]
      }]
    }
  }
}

resource "kubernetes_secret_v1" "runtime" {
  for_each = var.secret_bindings

  metadata {
    name      = each.key
    namespace = var.namespace
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
      "app.kubernetes.io/part-of"    = "fdai"
    }
  }

  data = {
    for environment_name, secret_name in each.value :
    environment_name => local.runtime_secret_values[secret_name]
  }
  type = "Opaque"

  lifecycle {
    ignore_changes = [data]
  }

  depends_on = [kubernetes_manifest.secret_provider]
}
