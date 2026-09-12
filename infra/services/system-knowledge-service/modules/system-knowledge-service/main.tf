resource "azurerm_user_assigned_identity" "service" {
  name                = "id-${var.name}"
  resource_group_name = var.platform.resource_group_name
  location            = var.platform.location
  tags                = merge(var.tags, { "fdai:component" = "system-knowledge-service" })
}

resource "azurerm_storage_container" "claims" {
  # checkov:skip=CKV2_AZURE_21:The platform document_blob diagnostic setting emits Blob read, write, and delete logs for this account.
  name                  = var.claim_store.container_name
  storage_account_id    = var.platform.claim_storage_account_id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.platform.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.service.principal_id
}

resource "azurerm_role_assignment" "claim_writer" {
  scope                = azurerm_storage_container.claims.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.service.principal_id
}

resource "azurerm_role_assignment" "principal_map_reader" {
  scope                = var.platform.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.service.principal_id
}

locals {
  claim_container_url      = "${trimsuffix(var.platform.claim_storage_blob_endpoint, "/")}/${azurerm_storage_container.claims.name}"
  bot_framework_enabled    = var.teams.transport == "bot_framework"
  outgoing_hmac_configured = var.teams.outgoing_hmac_secret_id != null
  container_secrets = concat(
    [{
      name                = "teams-principal-map"
      identity            = azurerm_user_assigned_identity.service.id
      key_vault_secret_id = var.teams.principal_map_secret_id
    }],
    local.outgoing_hmac_configured ? [{
      name                = "teams-outgoing-hmac"
      identity            = azurerm_user_assigned_identity.service.id
      key_vault_secret_id = var.teams.outgoing_hmac_secret_id
    }] : [],
  )
  common_environment = [
    { name = "FDAI_EXECUTION_VENUE", value = "deployed" },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID", value = azurerm_user_assigned_identity.service.client_id },
    { name = "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION", value = var.source_revision },
    { name = "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL", value = local.claim_container_url },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT", value = var.teams.transport },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID", value = var.teams.tenant_id },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON", value = jsonencode(var.teams.team_ids) },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON", value = jsonencode(var.teams.channel_ids) },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON", secret_name = "teams-principal-map" },
  ]
  bot_environment = local.bot_framework_enabled ? [
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID", value = azurerm_user_assigned_identity.service.client_id },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID", value = "28:${azurerm_user_assigned_identity.service.client_id}" },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON", value = jsonencode(var.teams.allowed_service_urls) },
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL", value = var.teams.jwks_url },
  ] : []
  outgoing_environment = local.outgoing_hmac_configured ? [
    { name = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET", secret_name = "teams-outgoing-hmac" },
  ] : []
  container_environment = concat(
    local.common_environment,
    local.bot_environment,
    local.outgoing_environment,
  )
}

module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = [azurerm_user_assigned_identity.service.id]
  registry_identity_id = azurerm_user_assigned_identity.service.id
  command              = ["fdai-system-knowledge-service"]
  args                 = []
  secrets              = local.container_secrets
  environment          = local.container_environment
  health               = var.health
  ingress              = { external_enabled = true, target_port = var.health.port }
  scaling              = var.scaling
  component            = "system-knowledge-service"
  rollback_strategy    = var.rollback.strategy
  tags                 = var.tags

  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.claim_writer,
    azurerm_role_assignment.principal_map_reader,
  ]
}

resource "azurerm_bot_service_azure_bot" "service" {
  count                         = local.bot_framework_enabled ? 1 : 0
  name                          = var.bot_name
  resource_group_name           = var.platform.resource_group_name
  location                      = "global"
  microsoft_app_id              = azurerm_user_assigned_identity.service.client_id
  microsoft_app_type            = "UserAssignedMSI"
  microsoft_app_msi_id          = azurerm_user_assigned_identity.service.id
  microsoft_app_tenant_id       = var.teams.tenant_id
  sku                           = "F0"
  endpoint                      = "https://${module.container_app.fqdn}/api/teams/messages"
  local_authentication_enabled  = false
  public_network_access_enabled = true
  streaming_endpoint_enabled    = false
  tags                          = merge(var.tags, { "fdai:component" = "system-knowledge-bot" })
}

resource "azurerm_bot_channel_ms_teams" "service" {
  count               = local.bot_framework_enabled ? 1 : 0
  bot_name            = azurerm_bot_service_azure_bot.service[0].name
  location            = azurerm_bot_service_azure_bot.service[0].location
  resource_group_name = var.platform.resource_group_name
  calling_enabled     = false
}

resource "terraform_data" "authority_contract" {
  input = {
    execution_authority = false
    identity_resource   = azurerm_user_assigned_identity.service.id
    replica_ceiling     = var.scaling.max_replicas
    teams_transport     = var.teams.transport
  }

  lifecycle {
    precondition {
      condition     = var.scaling.min_replicas == 1 && var.scaling.max_replicas == 1
      error_message = "System Knowledge Service must remain single-replica before promotion."
    }
    precondition {
      condition     = azurerm_user_assigned_identity.service.id != ""
      error_message = "System Knowledge Service requires a dedicated non-executor identity."
    }
  }
}
