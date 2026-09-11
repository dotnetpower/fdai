module "core_control_plane" {
  source = "./modules/core-control-plane"

  name                       = var.name
  platform                   = var.platform
  image                      = var.image
  source_revision            = var.source_revision
  bootstrap                  = var.bootstrap
  identity                   = var.identity
  rca_reader_identity        = var.rca_reader_identity
  event_topics               = var.event_topics
  teams_approval_destination = var.teams_approval_destination
  teams_notification_binding = var.teams_notification_binding
  stewardship_gitops         = var.stewardship_gitops
  database                   = var.database
  license                    = var.license
  # The runtime opens its health port before startup readiness runs, so liveness
  # answers immediately and no startup probe is needed to cover a slow boot.
  health                              = var.health
  rollback                            = var.rollback
  runtime_env                         = var.runtime_env
  stewardship_audit_interval_seconds  = var.stewardship_audit_interval_seconds
  handover_knowledge_interval_seconds = var.handover_knowledge_interval_seconds
  startup_readiness                   = var.startup_readiness
  llm                                 = var.llm
  runtime_call_evidence               = var.runtime_call_evidence
  observation_context                 = var.observation_context
  governed_rca                        = var.governed_rca
  configuration_drift                 = var.configuration_drift
  diagnostic_ingest                   = var.diagnostic_ingest
  decision_evidence_container_url     = var.decision_evidence_container_url
  operating_intent_source             = var.operating_intent_source
  scaling                             = var.scaling
  tags                                = var.tags
}
