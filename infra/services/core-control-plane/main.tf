module "core_control_plane" {
  source = "./modules/core-control-plane"

  name         = var.name
  platform     = var.platform
  image        = var.image
  bootstrap    = var.bootstrap
  identity     = var.identity
  event_topics = var.event_topics
  database     = var.database
  # The runtime opens its health port before startup readiness runs, so liveness
  # answers immediately and no startup probe is needed to cover a slow boot.
  health              = var.health
  rollback            = var.rollback
  runtime_env         = var.runtime_env
  startup_readiness   = var.startup_readiness
  llm                 = var.llm
  observation_context = var.observation_context
  configuration_drift = var.configuration_drift
  diagnostic_ingest   = var.diagnostic_ingest
  scaling             = var.scaling
  tags                = var.tags
}
