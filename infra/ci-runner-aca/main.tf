locals {
  tags = merge({
    "fdai:managed"    = "true"
    "fdai:workload"   = "ci"
    "fdai:env"        = "dev"
    "fdai:layer"      = "ci-runner-elastic"
    "fdai:managed-by" = "terraform"
    "fdai:vertical"   = "shared"
  }, var.additional_tags)

  repository_parts = split("/", var.github_repository)
  # Terraform never holds the GitHub credential. The operator sets the real value on the job
  # secret after apply, and lifecycle ignore_changes keeps later applies from overwriting it.
  credential_secret = "github-runner-credential"
}

resource "azurerm_resource_group" "ci" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "ci" {
  name                = "log-${var.name}"
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

# The registry holds only the runner image. Admin credentials stay disabled; the job pulls
# with a user-assigned identity that has AcrPull on this registry and nothing else.
resource "azurerm_container_registry" "ci" {
  # checkov:skip=CKV_AZURE_237:Dedicated data endpoints and the private-network controls below are Premium-only; this Basic registry holds one public-source runner image with no secrets.
  # checkov:skip=CKV_AZURE_139:Registry Tasks builds and the job pull need public network access on the Basic tier; admin credentials are disabled and the pull identity has AcrPull only.
  # checkov:skip=CKV_AZURE_163:The runner image is rebuilt from pinned inputs and carries no application data; the execution boundary is an ephemeral credential-free container.
  # checkov:skip=CKV_AZURE_167:Untagged-manifest retention is a Premium feature; the repository holds one image and each rebuild uses a new explicit tag.
  # checkov:skip=CKV_AZURE_166:Quarantine needs an external mark-verified writer; the image is built from this repository's pinned inputs by the operator.
  # checkov:skip=CKV_AZURE_233:Zone redundancy is Premium-only and region-dependent; a single-region CI registry is explicit and rebuildable.
  # checkov:skip=CKV_AZURE_164:Azure Content Trust is service-deprecated and Premium-only; the image is rebuilt from pinned inputs.
  # checkov:skip=CKV_AZURE_165:Geo-replication is Premium-only; this CI registry is explicitly single-region and rebuildable.
  name                = var.registry_name
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "pull" {
  name                = "id-${var.name}-pull"
  resource_group_name = azurerm_resource_group.ci.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "pull" {
  scope                = azurerm_container_registry.ci.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.pull.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_container_app_environment" "ci" {
  name                       = "cae-${var.name}"
  resource_group_name        = azurerm_resource_group.ci.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.ci.id
  tags                       = local.tags
}

resource "azurerm_container_app_job" "runner" {
  name                         = "caj-${var.name}"
  resource_group_name          = azurerm_resource_group.ci.name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.ci.id
  replica_timeout_in_seconds   = var.replica_timeout_seconds
  replica_retry_limit          = 0
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pull.id]
  }

  registry {
    server   = azurerm_container_registry.ci.login_server
    identity = azurerm_user_assigned_identity.pull.id
  }

  secret {
    name  = local.credential_secret
    value = "unset"
  }

  event_trigger_config {
    parallelism              = 1
    replica_completion_count = 1

    scale {
      min_executions              = 0
      max_executions              = var.max_executions
      polling_interval_in_seconds = 30

      rules {
        name             = "github-runner"
        custom_rule_type = "github-runner"
        metadata = {
          githubAPIURL              = "https://api.github.com"
          owner                     = local.repository_parts[0]
          runnerScope               = "repo"
          repos                     = local.repository_parts[1]
          targetWorkflowQueueLength = "1"
          labels                    = join(",", var.runner_labels)
        }
        authentication {
          secret_name       = local.credential_secret
          trigger_parameter = "personalAccessToken"
        }
      }
    }
  }

  template {
    container {
      name   = "runner"
      image  = "${azurerm_container_registry.ci.login_server}/${var.runner_image}"
      cpu    = var.job_cpu
      memory = var.job_memory

      env {
        name  = "GITHUB_REPOSITORY"
        value = var.github_repository
      }
      env {
        name  = "RUNNER_LABELS"
        value = join(",", var.runner_labels)
      }
      env {
        name        = "GITHUB_RUNNER_CREDENTIAL"
        secret_name = local.credential_secret
      }
    }
  }

  depends_on = [azurerm_role_assignment.pull]

  lifecycle {
    ignore_changes = [secret]
  }
}
