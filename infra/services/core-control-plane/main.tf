module "core_control_plane" {
  source = "./modules/core-control-plane"

  name         = var.name
  platform     = var.platform
  image        = var.image
  bootstrap    = var.bootstrap
  identity     = var.identity
  event_topics = var.event_topics
  database     = var.database
  # The runtime opens its health port only after startup readiness runs four phases, each
  # bounded by phase_timeout_seconds, so the startup budget is fixed here rather than left
  # to a caller-supplied health object that may omit it.
  health = merge(var.health, {
    startup_path          = coalesce(var.health.startup_path, var.health.liveness_path)
    startup_failure_count = coalesce(var.health.startup_failure_count, 90)
  })
  rollback          = var.rollback
  runtime_env       = var.runtime_env
  startup_readiness = var.startup_readiness
  scaling           = var.scaling
  tags              = var.tags
}
