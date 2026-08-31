module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = concat([var.identity.resource_id], var.identity.extra_resource_ids)
  registry_identity_id = var.identity.resource_id
  command              = ["fdai-core-control-plane"]
  args                 = []
  secrets = concat([{
    name                = "database-dsn"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.database.dsn_secret_id
    }], var.observation_context.enabled ? [{
    name                = "ohl-observation-signing-seed"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.observation_context.signing_seed_secret_id
  }] : [])
  environment = concat([
    { name = "FDAI_STATE_STORE_DSN", secret_name = "database-dsn" },
    { name = "POSTGRES_HOST", value = var.database.host },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "PGOPTIONS", value = "-c role=${var.database.role}" },
    { name = "FDAI_EXECUTION_VENUE", value = "deployed" },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "AZURE_TENANT_ID", value = var.bootstrap.azure_tenant_id },
    { name = "AZURE_SUBSCRIPTION_ID", value = var.bootstrap.azure_subscription_id },
    { name = "AZURE_REGION", value = var.bootstrap.azure_region },
    { name = "POSTGRES_DATABASE", value = var.bootstrap.postgres_database },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.client_id },
    { name = "LLM_MODE", value = "azure" },
    { name = "LLM_RESOLVED_MODELS_PATH", value = "/app/resolved-models.json" },
    { name = "FDAI_LLM_ENDPOINT", value = trimspace(var.llm.endpoint) },
    { name = "FDAI_WEB_SEARCH_ENABLED", value = tostring(var.llm.web_search_enabled) },
    { name = "FDAI_WEB_SEARCH_ALLOWED_DOMAINS", value = join(",", var.llm.web_search_allowed_domains) },
    { name = "FDAI_WEB_SEARCH_MAX_RESULTS", value = tostring(var.llm.web_search_max_results) },
    { name = "FDAI_WEB_SEARCH_TIMEOUT_SECONDS", value = tostring(var.llm.web_search_timeout_seconds) },
    { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
    { name = "KAFKA_TOPIC_EVENTS", value = var.event_topics.events },
    { name = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.operational_kafka_bootstrap_servers },
    { name = "FDAI_CANARY_TOPIC", value = var.event_topics.canary },
    { name = "FDAI_INVENTORY_RAW_TOPIC", value = var.event_topics.inventory_raw },
    { name = "FDAI_STARTUP_KAFKA_PROBE_TOPIC", value = var.event_topics.startup_probe },
    { name = "FDAI_STARTUP_KAFKA_SETTLE_SECONDS", value = tostring(var.startup_readiness.kafka_settle_seconds) },
    { name = "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS", value = tostring(var.startup_readiness.probe_timeout_seconds) },
    { name = "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS", value = tostring(var.startup_readiness.phase_timeout_seconds) },
    { name = "FDAI_EXECUTOR_COMMAND_TOPIC", value = var.event_topics.executor_command },
    { name = "FDAI_EXECUTOR_RECEIPT_TOPIC", value = var.event_topics.executor_receipt },
    { name = "FDAI_HIL_DECISION_TOPIC", value = var.event_topics.hil_decisions },
    { name = "FDAI_STAGE_TOPIC", value = var.event_topics.pipeline_stages },
    { name = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC", value = var.event_topics.semantic_requests },
    { name = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", value = var.event_topics.semantic_projections },
    { name = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC", value = var.event_topics.semantic_physical },
    { name = "FDAI_READ_INVESTIGATION_REQUEST_TOPIC", value = var.event_topics.read_investigation_requests },
    { name = "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC", value = var.event_topics.incident_intervention_requests },
    { name = "FDAI_START_CONSUMER", value = "1" },
    { name = "FDAI_HEALTH_PORT", value = tostring(var.health.port) },
    ], var.teams_approval_destination.team_id == "" ? [] : [
    { name = "FDAI_TEAMS_APPROVAL_TEAM_ID", value = var.teams_approval_destination.team_id },
    { name = "FDAI_TEAMS_APPROVAL_CHANNEL_ID", value = var.teams_approval_destination.channel_id },
    { name = "FDAI_TEAMS_APPROVAL_ACTIVITY_URL", value = var.teams_approval_destination.activity_url },
    ], !var.observation_context.enabled ? [] : [
    { name = "FDAI_OHL_OBSERVATION_SIGNING_SEED", secret_name = "ohl-observation-signing-seed" },
    { name = "FDAI_OHL_OBSERVER_IDENTITY", value = "observer:heimdall:azure-container-apps" },
    { name = "FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE", value = "azure-managed-identity:${var.identity.client_id}" },
    { name = "FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE", value = var.observation_context.executor_credential_lineage },
    { name = "FDAI_OHL_SOURCE_IDENTITY", value = "source:promoted-azure-inventory" },
    { name = "FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE", value = var.observation_context.source_credential_lineage },
    { name = "FDAI_OHL_VERIFIER_IDENTITY", value = "observation-verifier:ohl-ed25519" },
    ], length(var.llm.model_endpoints) == 0 ? [] : [
    { name = "FDAI_MODEL_ENDPOINTS_JSON", value = jsonencode(var.llm.model_endpoints) },
    ], var.llm.resolved_models_digest == "" ? [] : [
    { name = "LLM_RESOLVED_MODELS_SHA256", value = var.llm.resolved_models_digest },
    ], !var.configuration_drift.enabled ? [] : [
    { name = "FDAI_CONFIGURATION_DRIFT_ENABLED", value = "1" },
    { name = "FDAI_CONFIGURATION_BASELINE_PATH", value = var.configuration_drift.baseline_path },
    { name = "FDAI_CONFIGURATION_BASELINE_VERSION", value = var.configuration_drift.baseline_version },
    { name = "FDAI_CONFIGURATION_BASELINE_SHA256", value = var.configuration_drift.baseline_sha256 },
    { name = "FDAI_CONFIGURATION_SCOPE", value = var.configuration_drift.scope },
    { name = "FDAI_CONFIGURATION_SUBSCRIPTIONS_JSON", value = jsonencode(var.configuration_drift.subscription_scopes) },
    { name = "FDAI_CONFIGURATION_ATTRIBUTE_PATHS_JSON", value = jsonencode(var.configuration_drift.attribute_paths) },
    { name = "FDAI_CONFIGURATION_ARG_ENDPOINT", value = var.configuration_drift.arg_endpoint },
    ], !var.diagnostic_ingest.enabled ? [] : [
    { name = "FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS", value = var.diagnostic_ingest.bootstrap_servers },
    { name = "FDAI_DIAGNOSTIC_TOPIC", value = var.diagnostic_ingest.topic },
    { name = "FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON", value = jsonencode(var.diagnostic_ingest.metric_whitelist) },
    { name = "FDAI_DIAGNOSTIC_CONSUMER_GROUP_ID", value = var.diagnostic_ingest.consumer_group_id },
  ])
  health            = var.health
  scaling           = var.scaling
  component         = "core-control-plane"
  rollback_strategy = var.rollback.strategy
  tags              = var.tags
}
