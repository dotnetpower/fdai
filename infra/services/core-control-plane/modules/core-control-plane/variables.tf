variable "name" { type = string }
variable "platform" {
  type = object({
    resource_group_name          = string
    container_app_environment_id = string
    acr_login_server             = string
    kafka_bootstrap_servers      = string
  })
}
variable "image" { type = string }
variable "identity" {
  type = object({
    resource_id        = string
    client_id          = string
    extra_resource_ids = optional(list(string), [])
  })
}
variable "event_topics" {
  type = object({
    events           = string
    executor_command = string
    executor_receipt = string
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
variable "scaling" {
  type = object({
    min_replicas = number
    max_replicas = number
    cpu          = number
    memory       = string
  })
}
variable "tags" { type = map(string) }
