module "core_control_plane" {
  source = "./modules/core-control-plane"

  name         = var.name
  platform     = var.platform
  image        = var.image
  bootstrap    = var.bootstrap
  identity     = var.identity
  event_topics = var.event_topics
  database     = var.database
  health       = var.health
  rollback     = var.rollback
  runtime_env  = var.runtime_env
  scaling      = var.scaling
  tags         = var.tags
}
