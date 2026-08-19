module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = [var.identity.runtime_resource_id, var.identity.command_resource_id]
  registry_identity_id = var.identity.runtime_resource_id
  command              = ["fdai-operator-service"]
  args                 = []
  secrets = [{
    name                = "database-dsn"
    identity            = var.identity.runtime_resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }]
  environment = [
    { name = "FDAI_DATABASE_URL", secret_name = "database-dsn" },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "PGOPTIONS", value = "-c role=${var.database.role}" },
    { name = "FDAI_EXECUTION_VENUE", value = "deployed" },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.runtime_client_id },
    { name = "FDAI_COMMAND_MI_CLIENT_ID", value = var.identity.command_client_id },
    { name = "FDAI_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
    { name = "KAFKA_TOPIC_EVENTS", value = var.event_topics.events },
    { name = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC", value = var.event_topics.semantic_requests },
    { name = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", value = var.event_topics.semantic_projections },
    { name = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC", value = var.event_topics.semantic_physical },
    { name = "FDAI_ENTRA_TENANT_ID", value = var.auth.tenant_id },
    { name = "FDAI_API_AUDIENCE", value = var.auth.api_audience },
    { name = "FDAI_RBAC_READERS_GROUP_ID", value = var.rbac.readers_group_id },
    { name = "FDAI_RBAC_CONTRIBUTORS_GROUP_ID", value = var.rbac.contributors_group_id },
    { name = "FDAI_RBAC_APPROVERS_GROUP_ID", value = var.rbac.approvers_group_id },
    { name = "FDAI_RBAC_OWNERS_GROUP_ID", value = var.rbac.owners_group_id },
    { name = "FDAI_RBAC_BREAK_GLASS_GROUP_ID", value = var.rbac.break_glass_group_id },
    { name = "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS", value = var.cors_allow_origins },
    { name = "FDAI_OPERATOR_SERVICE_PORT", value = tostring(var.health.port) },
  ]
  health            = var.health
  ingress           = { external_enabled = true, target_port = var.health.port }
  scaling           = var.scaling
  component         = "operator-service"
  rollback_strategy = var.rollback.strategy
  tags              = var.tags
}

locals {
  channel_edge_enabled_channels = join(",", compact([
    var.channel_edge.slack_enabled ? "slack" : "",
    var.channel_edge.teams_enabled ? "teams" : "",
  ]))
  channel_edge_secrets = concat(
    [
      {
        name                = "edge-database-dsn"
        identity            = var.identity.edge_resource_id
        key_vault_secret_id = var.database.dsn_secret_id
      },
      {
        name                = "edge-principal-scopes"
        identity            = var.identity.edge_resource_id
        key_vault_secret_id = var.channel_edge.principal_scopes_secret_id
      },
    ],
    var.channel_edge.slack_enabled ? [
      {
        name                = "slack-signing-secret"
        identity            = var.identity.edge_resource_id
        key_vault_secret_id = var.channel_edge.slack_signing_secret_id
      },
      {
        name                = "slack-bot-token"
        identity            = var.identity.edge_resource_id
        key_vault_secret_id = var.channel_edge.slack_bot_token_secret_id
      },
      {
        name                = "slack-principal-map"
        identity            = var.identity.edge_resource_id
        key_vault_secret_id = var.channel_edge.slack_principal_map_secret_id
      },
    ] : [],
    var.channel_edge.teams_enabled ? [
      {
        name                = "teams-principal-map"
        identity            = var.identity.edge_resource_id
        key_vault_secret_id = var.channel_edge.teams_principal_map_secret_id
      },
    ] : [],
  )
  channel_edge_environment = concat(
    [
      { name = "FDAI_DATABASE_URL", secret_name = "edge-database-dsn" },
      { name = "FDAI_DATABASE_ROLE", value = var.database.role },
      { name = "PGOPTIONS", value = "-c role=${var.database.role}" },
      { name = "FDAI_EXECUTION_VENUE", value = "deployed" },
      { name = "RUNTIME_ENV", value = var.runtime_env },
      { name = "FDAI_CHANNEL_EDGE_MI_CLIENT_ID", value = var.identity.edge_client_id },
      { name = "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS", value = local.channel_edge_enabled_channels },
      { name = "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON", secret_name = "edge-principal-scopes" },
      { name = "FDAI_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
      { name = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC", value = var.event_topics.semantic_requests },
      { name = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", value = var.event_topics.semantic_projections },
      { name = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC", value = var.event_topics.semantic_physical },
      { name = "FDAI_CHANNEL_EDGE_PORT", value = tostring(var.channel_edge.health.port) },
    ],
    var.channel_edge.slack_enabled ? [
      { name = "FDAI_SLACK_SIGNING_SECRET", secret_name = "slack-signing-secret" },
      { name = "FDAI_SLACK_BOT_TOKEN", secret_name = "slack-bot-token" },
      { name = "FDAI_SLACK_TEAM_ID", value = var.channel_edge.slack_team_id },
      { name = "FDAI_SLACK_PRINCIPAL_MAP_JSON", secret_name = "slack-principal-map" },
    ] : [],
    var.channel_edge.teams_enabled ? [
      { name = "FDAI_TEAMS_APPLICATION_ID", value = var.channel_edge.teams_application_id },
      { name = "FDAI_TEAMS_TENANT_ID", value = var.channel_edge.teams_tenant_id },
      { name = "FDAI_TEAMS_PRINCIPAL_MAP_JSON", secret_name = "teams-principal-map" },
      { name = "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON", value = var.channel_edge.teams_allowed_service_urls },
      { name = "FDAI_TEAMS_JWKS_URL", value = var.channel_edge.teams_jwks_url },
    ] : [],
  )
}

resource "terraform_data" "channel_edge_contract" {
  count = var.channel_edge.enabled ? 1 : 0

  lifecycle {
    precondition {
      condition     = var.identity.edge_resource_id != "" && var.identity.edge_client_id != ""
      error_message = "Enabled channel_edge requires one dedicated non-executor workload identity."
    }
    precondition {
      condition     = var.event_topics.semantic_requests != "" && var.event_topics.semantic_projections != ""
      error_message = "Enabled channel_edge requires semantic request and projection topics."
    }
  }
}

module "channel_edge" {
  count  = var.channel_edge.enabled ? 1 : 0
  source = "../../../_modules/container-app"

  name                 = var.channel_edge.name
  platform             = var.platform
  image                = var.image
  identity_ids         = [var.identity.edge_resource_id]
  registry_identity_id = var.identity.edge_resource_id
  command              = ["fdai-operator-channel-edge"]
  args                 = []
  secrets              = local.channel_edge_secrets
  environment          = local.channel_edge_environment
  health               = var.channel_edge.health
  ingress              = { external_enabled = true, target_port = var.channel_edge.health.port }
  scaling              = var.channel_edge.scaling
  component            = "operator-channel-edge"
  rollback_strategy    = var.rollback.strategy
  tags                 = var.tags
  depends_on           = [terraform_data.channel_edge_contract]
}
