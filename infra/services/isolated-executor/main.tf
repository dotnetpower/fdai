module "isolated_executor" {
  source = "./modules/isolated-executor"

  name         = var.name
  platform     = var.platform
  image        = var.image
  identity     = var.identity
  event_topics = var.event_topics
  database     = var.database
  health       = var.health
  rollback     = var.rollback
  runtime_env  = var.runtime_env
  authority    = var.authority
  scaling      = var.scaling
  tags         = var.tags
}
