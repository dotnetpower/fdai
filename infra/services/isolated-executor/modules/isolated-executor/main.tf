module "container_app" {
  source = "../../../_modules/container-app"

  name     = var.name
  platform = var.platform
  image    = var.image
  identity_ids = concat(
    [var.identity.transport_resource_id],
    var.authority.cutover ? [
      var.identity.change_resource_id,
      var.identity.resilience_resource_id,
      var.identity.finops_resource_id,
    ] : []
  )
  registry_identity_id = var.identity.transport_resource_id
  command              = ["fdai-isolated-executor-service"]
  args                 = []
  secrets = [{
    name                = "database-dsn"
    identity            = var.identity.transport_resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }]
  environment = [
    { name = "FDAI_STATE_STORE_DSN", secret_name = "database-dsn" },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.transport_client_id },
    { name = "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID", value = var.identity.transport_client_id },
    { name = "FDAI_CHANGE_MI_CLIENT_ID", value = var.authority.cutover ? var.identity.change_client_id : "" },
    { name = "FDAI_RESILIENCE_MI_CLIENT_ID", value = var.authority.cutover ? var.identity.resilience_client_id : "" },
    { name = "FDAI_FINOPS_MI_CLIENT_ID", value = var.authority.cutover ? var.identity.finops_client_id : "" },
    { name = "FDAI_ISOLATED_EXECUTOR_DEPLOYED", value = "1" },
    { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers },
    { name = "FDAI_EXECUTOR_COMMAND_TOPIC", value = var.event_topics.command },
    { name = "FDAI_EXECUTOR_RECEIPT_TOPIC", value = var.event_topics.receipt },
    { name = "KAFKA_TOPIC_DLQ_SUFFIX", value = var.event_topics.dlq_suffix },
    { name = "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", value = var.authority.cutover ? "1" : "0" },
    { name = "FDAI_DEV_OPERATIONS_GATEWAY_URL", value = var.authority.dev_operations_gateway_url },
    { name = "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE", value = var.authority.dev_operations_gateway_audience },
    { name = "FDAI_ISOLATED_EXECUTOR_HEALTH_PORT", value = tostring(var.health.port) },
  ]
  health            = var.health
  scaling           = var.scaling
  component         = "isolated-executor"
  rollback_strategy = var.rollback.strategy
  tags              = merge(var.tags, { "fdai:authority-cutover" = tostring(var.authority.cutover) })
}
