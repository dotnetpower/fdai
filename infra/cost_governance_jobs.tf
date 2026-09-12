// Optional Cost Governance package jobs are isolated from the broad compute
// module dependency graph. They bind existing platform prerequisites by exact
// identity and remain absent until a deployment supplies both schedules.

locals {
  cost_governance_jobs_enabled = (
    var.cost_governance_collector_cron_expression != "" ||
    var.cost_governance_analyzer_cron_expression != ""
  )
  cost_governance_job_configured = (
    var.cost_governance_image != "" &&
    var.cost_governance_scope_id != "" &&
    var.cost_governance_known_service_ids_json != "" &&
    var.cost_governance_ontology_release_id != "" &&
    var.cost_governance_ontology_release_digest != ""
  )
  cost_governance_job_name_prefix = "caj-${var.workload}${local.env_suffix}"
  cost_governance_resource_group  = "rg-${var.workload}${local.full_suffix}"
  cost_governance_environment     = "cae-${var.workload}${local.full_suffix}"
  cost_governance_inventory_identity = (
    "id-${var.workload}${local.full_suffix}-inventory"
  )
  cost_governance_state_store_dsn_secret_uri = join("", [
    "https://kv-${var.workload}${local.full_suffix}${local.global_name_suffix}",
    ".vault.azure.net/secrets/fdai-state-store-dsn",
  ])
  cost_governance_job_env = {
    FDAI_COST_SCOPE_ID                = var.cost_governance_scope_id
    FDAI_COST_KNOWN_SERVICE_IDS       = var.cost_governance_known_service_ids_json
    FDAI_COST_ONTOLOGY_RELEASE_ID     = var.cost_governance_ontology_release_id
    FDAI_COST_ONTOLOGY_RELEASE_DIGEST = var.cost_governance_ontology_release_digest
    FDAI_COST_COLLECTION_MI_CLIENT_ID = try(data.azurerm_user_assigned_identity.cost_governance_inventory[0].client_id, "")
  }
}

data "azurerm_container_app_environment" "cost_governance" {
  count = local.cost_governance_jobs_enabled ? 1 : 0

  name                = local.cost_governance_environment
  resource_group_name = local.cost_governance_resource_group
}

data "azurerm_user_assigned_identity" "cost_governance_inventory" {
  count = local.cost_governance_jobs_enabled ? 1 : 0

  name                = local.cost_governance_inventory_identity
  resource_group_name = local.cost_governance_resource_group
}

moved {
  from = module.compute.azurerm_container_app_job.cost_governance_collector[0]
  to   = azurerm_container_app_job.cost_governance_collector[0]
}

moved {
  from = module.compute.azurerm_container_app_job.cost_governance_analyzer[0]
  to   = azurerm_container_app_job.cost_governance_analyzer[0]
}

resource "azurerm_container_app_job" "cost_governance_collector" {
  count = var.cost_governance_collector_cron_expression == "" ? 0 : 1

  name                         = "${local.cost_governance_job_name_prefix}-cost-collect"
  container_app_environment_id = data.azurerm_container_app_environment.cost_governance[0].id
  resource_group_name          = local.cost_governance_resource_group
  location                     = var.region
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 180
  replica_retry_limit          = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.cost_governance_inventory[0].id]
  }

  registry {
    server   = split("/", var.cost_governance_image)[0]
    identity = data.azurerm_user_assigned_identity.cost_governance_inventory[0].id
  }

  secret {
    name                = "cost-store-dsn"
    identity            = data.azurerm_user_assigned_identity.cost_governance_inventory[0].id
    key_vault_secret_id = local.cost_governance_state_store_dsn_secret_uri
  }

  schedule_trigger_config {
    cron_expression          = var.cost_governance_collector_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "cost-governance-collector"
      image   = var.cost_governance_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["fdai-cost-collector"]

      dynamic "env" {
        for_each = local.cost_governance_job_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "FDAI_COST_STORE_DSN"
        secret_name = "cost-store-dsn"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = local.cost_governance_job_configured
      error_message = "Cost Governance collector requires image, scope, services, and exact ontology release."
    }
  }

  tags = local.tags
}

resource "azurerm_container_app_job" "cost_governance_analyzer" {
  count = var.cost_governance_analyzer_cron_expression == "" ? 0 : 1

  name                         = "${local.cost_governance_job_name_prefix}-cost-analyze"
  container_app_environment_id = data.azurerm_container_app_environment.cost_governance[0].id
  resource_group_name          = local.cost_governance_resource_group
  location                     = var.region
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 180
  replica_retry_limit          = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.cost_governance_inventory[0].id]
  }

  registry {
    server   = split("/", var.cost_governance_image)[0]
    identity = data.azurerm_user_assigned_identity.cost_governance_inventory[0].id
  }

  secret {
    name                = "cost-store-dsn"
    identity            = data.azurerm_user_assigned_identity.cost_governance_inventory[0].id
    key_vault_secret_id = local.cost_governance_state_store_dsn_secret_uri
  }

  schedule_trigger_config {
    cron_expression          = var.cost_governance_analyzer_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "cost-governance-analyzer"
      image   = var.cost_governance_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["fdai-cost-analyzer"]

      dynamic "env" {
        for_each = merge(local.cost_governance_job_env, {
          KAFKA_BOOTSTRAP_SERVERS   = module.event_bus.kafka_bootstrap
          FDAI_COST_RAW_EVENT_TOPIC = local.event_topics[0]
        })
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "FDAI_COST_STORE_DSN"
        secret_name = "cost-store-dsn"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = local.cost_governance_job_configured
      error_message = "Cost Governance analyzer requires image, scope, services, and exact ontology release."
    }
  }

  tags = local.tags
}