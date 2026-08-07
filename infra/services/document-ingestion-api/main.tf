module "document_ingestion_api" {
  source = "./modules/document-ingestion-api"

  name               = var.name
  platform           = var.platform
  image              = var.image
  identity           = var.identity
  event_topics       = var.event_topics
  database           = var.database
  document_store     = var.document_store
  health             = var.health
  rollback           = var.rollback
  runtime_env        = var.runtime_env
  auth               = var.auth
  cors_allow_origins = var.cors_allow_origins
  scaling            = var.scaling
  tags               = var.tags
}
