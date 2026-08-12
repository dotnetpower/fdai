module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = [var.identity.resource_id]
  registry_identity_id = var.identity.resource_id
  command              = ["fdai-document-processing-worker"]
  args                 = []
  sidecars = [{
    name   = "clamav"
    image  = var.clamav.image
    cpu    = var.clamav.cpu
    memory = var.clamav.memory
    startup_probe = {
      transport               = "TCP"
      port                    = var.clamav.port
      failure_count_threshold = 30
    }
    liveness_probe = {
      transport = "TCP"
      port      = var.clamav.port
    }
    readiness_probe = {
      transport = "TCP"
      port      = var.clamav.port
    }
  }]
  secrets = [{
    name                = "database-dsn"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }]
  environment = [
    { name = "FDAI_DATABASE_URL", secret_name = "database-dsn" },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "PGOPTIONS", value = "-c role=${var.database.role}" },
    { name = "FDAI_INGESTION_DEPLOYMENT_ROLE", value = "worker" },
    { name = "FDAI_EXECUTION_VENUE", value = "deployed" },
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
    { name = "FDAI_CLAMAV_HOST", value = var.clamav.host },
    { name = "FDAI_CLAMAV_PORT", value = tostring(var.clamav.port) },
  ]
  health            = var.health
  scaling           = var.scaling
  component         = "document-processing-worker"
  rollback_strategy = var.rollback.strategy
  tags              = var.tags
}
