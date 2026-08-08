module "document_processing_worker" {
  source = "./modules/document-processing-worker"

  name           = var.name
  platform       = var.platform
  image          = var.image
  clamav         = var.clamav
  identity       = var.identity
  event_topics   = var.event_topics
  database       = var.database
  document_store = var.document_store
  health         = var.health
  rollback       = var.rollback
  runtime_env    = var.runtime_env
  embedding      = var.embedding
  scaling        = var.scaling
  tags           = var.tags
}
