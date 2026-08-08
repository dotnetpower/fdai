module "operator_service" {
  source = "./modules/operator-service"

  name               = var.name
  platform           = var.platform
  image              = var.image
  identity           = var.identity
  event_topics       = var.event_topics
  database           = var.database
  health             = var.health
  rollback           = var.rollback
  runtime_env        = var.runtime_env
  auth               = var.auth
  rbac               = var.rbac
  cors_allow_origins = var.cors_allow_origins
  scaling            = var.scaling
  tags               = var.tags
}
