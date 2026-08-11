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
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.runtime_client_id },
    { name = "FDAI_COMMAND_MI_CLIENT_ID", value = var.identity.command_client_id },
    { name = "FDAI_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
    { name = "KAFKA_TOPIC_EVENTS", value = var.event_topics.events },
    { name = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC", value = var.event_topics.semantic_requests },
    { name = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", value = var.event_topics.semantic_projections },
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
