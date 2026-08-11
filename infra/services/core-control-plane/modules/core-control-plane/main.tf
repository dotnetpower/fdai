module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = concat([var.identity.resource_id], var.identity.extra_resource_ids)
  registry_identity_id = var.identity.resource_id
  command              = ["fdai-core-control-plane"]
  args                 = []
  secrets = [{
    name                = "database-dsn"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }]
  environment = [
    { name = "FDAI_STATE_STORE_DSN", secret_name = "database-dsn" },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "PGOPTIONS", value = "-c role=${var.database.role}" },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "AZURE_TENANT_ID", value = var.bootstrap.azure_tenant_id },
    { name = "AZURE_SUBSCRIPTION_ID", value = var.bootstrap.azure_subscription_id },
    { name = "AZURE_REGION", value = var.bootstrap.azure_region },
    { name = "POSTGRES_HOST", value = var.bootstrap.postgres_host },
    { name = "POSTGRES_DATABASE", value = var.bootstrap.postgres_database },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.client_id },
    { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
    { name = "KAFKA_TOPIC_EVENTS", value = var.event_topics.events },
    { name = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.operational_kafka_bootstrap_servers },
    { name = "FDAI_STARTUP_KAFKA_PROBE_TOPIC", value = var.event_topics.startup_probe },
    { name = "FDAI_STARTUP_KAFKA_SETTLE_SECONDS", value = tostring(var.startup_readiness.kafka_settle_seconds) },
    { name = "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS", value = tostring(var.startup_readiness.probe_timeout_seconds) },
    { name = "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS", value = tostring(var.startup_readiness.phase_timeout_seconds) },
    { name = "FDAI_EXECUTOR_COMMAND_TOPIC", value = var.event_topics.executor_command },
    { name = "FDAI_EXECUTOR_RECEIPT_TOPIC", value = var.event_topics.executor_receipt },
    { name = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC", value = var.event_topics.semantic_requests },
    { name = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", value = var.event_topics.semantic_projections },
    { name = "FDAI_START_CONSUMER", value = "1" },
    { name = "FDAI_HEALTH_PORT", value = tostring(var.health.port) },
  ]
  health            = var.health
  scaling           = var.scaling
  component         = "core-control-plane"
  rollback_strategy = var.rollback.strategy
  tags              = var.tags
}
