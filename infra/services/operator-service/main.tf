module "operator_service" {
  source = "./modules/operator-service"

  name                           = var.name
  platform                       = var.platform
  image                          = var.image
  identity                       = var.identity
  runtime_call_evidence          = var.runtime_call_evidence
  event_topics                   = var.event_topics
  database                       = var.database
  health                         = var.health
  rollback                       = var.rollback
  runtime_env                    = var.runtime_env
  auth                           = var.auth
  rbac                           = var.rbac
  cors_allow_origins             = var.cors_allow_origins
  notification_receipt_secret_id = var.notification_receipt_secret_id
  cost_pseudonym_key_secret_id   = var.cost_pseudonym_key_secret_id
  scaling                        = var.scaling
  channel_edge                   = var.channel_edge
  hil_callback                   = var.hil_callback
  tags                           = var.tags
}
