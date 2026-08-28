// Optional package jobs. Both use the read-only inventory identity, which is
// distinct from identity/finops (Thor's Cost Governance execution principal).
// A disabled package still performs only its authoritative activation read;
// collector transport and analyzer publication remain untouched.

locals {
  cost_governance_job_configured = (
    var.cost_governance_image != "" &&
    var.cost_governance_scope_id != "" &&
    var.cost_governance_known_service_ids_json != "" &&
    var.cost_governance_ontology_release_id != "" &&
    var.cost_governance_ontology_release_digest != ""
  )
  cost_governance_job_env = {
    FDAI_COST_SCOPE_ID                = var.cost_governance_scope_id
    FDAI_COST_KNOWN_SERVICE_IDS       = var.cost_governance_known_service_ids_json
    FDAI_COST_ONTOLOGY_RELEASE_ID     = var.cost_governance_ontology_release_id
    FDAI_COST_ONTOLOGY_RELEASE_DIGEST = var.cost_governance_ontology_release_digest
    FDAI_COST_COLLECTION_MI_CLIENT_ID = var.inventory_identity_client_id
  }
}

resource "azurerm_container_app_job" "cost_governance_collector" {
  count = var.cost_governance_collector_cron_expression == "" ? 0 : 1

  name                         = "${local.core_job_name_prefix}-cost-collect"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 180
  replica_retry_limit          = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [var.inventory_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.inventory_identity_id
    }
  }

  secret {
    name                = "cost-store-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
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

  tags = var.tags
}

resource "azurerm_container_app_job" "cost_governance_analyzer" {
  count = var.cost_governance_analyzer_cron_expression == "" ? 0 : 1

  name                         = "${local.core_job_name_prefix}-cost-analyze"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 180
  replica_retry_limit          = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [var.inventory_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.inventory_identity_id
    }
  }

  secret {
    name                = "cost-store-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
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
          KAFKA_BOOTSTRAP_SERVERS   = var.kafka_bootstrap_servers
          FDAI_COST_RAW_EVENT_TOPIC = var.kafka_topic_events
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

  tags = var.tags
}
