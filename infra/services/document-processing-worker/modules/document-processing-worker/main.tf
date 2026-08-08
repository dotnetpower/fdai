module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = [var.identity.resource_id]
  registry_identity_id = var.identity.resource_id
  command              = ["fdai-document-processing-worker"]
  args                 = []
  secrets = [{
    name                = "database-dsn"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }]
  environment = [
    { name = "FDAI_DATABASE_URL", secret_name = "database-dsn" },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "FDAI_INGESTION_DEPLOYMENT_ROLE", value = "worker" },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.client_id },
    { name = "FDAI_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
    { name = "FDAI_DOCUMENT_EVENT_TOPIC", value = var.event_topics.pipeline_stages },
    { name = "FDAI_PANTHEON_OBJECT_TOPIC", value = var.event_topics.pantheon_objects },
    { name = "FDAI_EMBEDDING_ENDPOINT", value = var.embedding.endpoint },
    { name = "FDAI_EMBEDDING_DEPLOYMENT", value = var.embedding.deployment },
    { name = "FDAI_ADLS_ACCOUNT_NAME", value = var.document_store.account_name },
    { name = "FDAI_ADLS_ACCOUNT_URL", value = var.document_store.account_url },
    { name = "FDAI_ADLS_SOURCE_FILE_SYSTEM", value = var.document_store.source_file_system },
    { name = "FDAI_ADLS_DERIVED_FILE_SYSTEM", value = var.document_store.derived_file_system },
    { name = "FDAI_INGESTION_WORKER_HEALTH_PORT", value = tostring(var.health.port) },
  ]
  health            = var.health
  scaling           = var.scaling
  component         = "document-processing-worker"
  rollback_strategy = var.rollback.strategy
  tags              = var.tags
}
