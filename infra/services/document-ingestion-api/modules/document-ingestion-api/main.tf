module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = [var.identity.resource_id]
  registry_identity_id = var.identity.resource_id
  command              = ["fdai-document-ingestion-api"]
  args                 = []
  secrets = [{
    name                = "database-dsn"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }]
  environment = [
    { name = "FDAI_DATABASE_URL", secret_name = "database-dsn" },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "FDAI_INGESTION_DEPLOYMENT_ROLE", value = "api" },
    { name = "FDAI_INGESTION_COHOST_WORKER", value = "0" },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.client_id },
    { name = "FDAI_ENTRA_TENANT_ID", value = var.auth.tenant_id },
    { name = "FDAI_API_AUDIENCE", value = var.auth.api_audience },
    { name = "FDAI_RBAC_READERS_GROUP_ID", value = var.rbac.readers_group_id },
    { name = "FDAI_RBAC_CONTRIBUTORS_GROUP_ID", value = var.rbac.contributors_group_id },
    { name = "FDAI_RBAC_APPROVERS_GROUP_ID", value = var.rbac.approvers_group_id },
    { name = "FDAI_RBAC_OWNERS_GROUP_ID", value = var.rbac.owners_group_id },
    { name = "FDAI_RBAC_BREAK_GLASS_GROUP_ID", value = var.rbac.break_glass_group_id },
    { name = "FDAI_INGESTION_CORS_ALLOW_ORIGINS", value = var.cors_allow_origins },
    { name = "FDAI_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
    { name = "FDAI_DOCUMENT_EVENT_TOPIC", value = var.event_topics.pipeline_stages },
    { name = "FDAI_EMBEDDING_ENDPOINT", value = var.embedding.endpoint },
    { name = "FDAI_EMBEDDING_DEPLOYMENT", value = var.embedding.deployment },
    { name = "FDAI_ADLS_ACCOUNT_NAME", value = var.document_store.account_name },
    { name = "FDAI_ADLS_ACCOUNT_URL", value = var.document_store.account_url },
    { name = "FDAI_ADLS_SOURCE_FILE_SYSTEM", value = var.document_store.source_file_system },
  ]
  health            = var.health
  ingress           = { external_enabled = true, target_port = var.health.port }
  scaling           = var.scaling
  component         = "document-ingestion-api"
  rollback_strategy = var.rollback.strategy
  tags              = var.tags
}
