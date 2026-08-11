variable "name" { type = string }
variable "platform" {
  type = object({
    resource_group_name                 = string
    container_app_environment_id        = string
    acr_login_server                    = string
    kafka_bootstrap_servers             = string
    operational_kafka_bootstrap_servers = optional(string, "")
  })
}
variable "image" { type = string }
variable "bootstrap" {
  type = object({
    azure_tenant_id       = string
    azure_subscription_id = string
    azure_region          = string
    postgres_host         = string
    postgres_database     = string
  })
}
variable "identity" {
  type = object({
    resource_id        = string
    client_id          = string
    extra_resource_ids = optional(list(string), [])
  })
}
variable "event_topics" {
  type = object({
    events               = string
    executor_command     = string
    executor_receipt     = string
    startup_probe        = optional(string, "runtime.startup.probe")
    semantic_requests    = optional(string, "")
    semantic_projections = optional(string, "")
  })
}
variable "database" {
  type = object({
    dsn_secret_id = string
    role          = string
  })
  sensitive = true
}
variable "health" {
  type = object({
    port                    = number
    liveness_path           = string
    readiness_path          = string
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
  })
}
variable "rollback" {
  type = object({
    strategy                 = string
    previous_image           = string
    max_unavailable_replicas = optional(number, 0)
  })
}
variable "runtime_env" { type = string }
variable "startup_readiness" {
  type = object({
    kafka_settle_seconds  = number
    probe_timeout_seconds = number
    phase_timeout_seconds = number
  })
}
variable "scaling" {
  type = object({
    min_replicas = number
    max_replicas = number
    cpu          = number
    memory       = string
  })
}
variable "tags" { type = map(string) }
