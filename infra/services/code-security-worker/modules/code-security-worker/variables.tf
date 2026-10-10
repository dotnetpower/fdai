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
variable "identity" { type = object({ resource_id = string, client_id = string }) }
variable "database" {
  type      = object({ dsn_secret_id = string, host = string, role = string })
  sensitive = true
}
variable "github" {
  type = object({
    app_client_id             = optional(string, "")
    app_installation_id       = optional(string, "")
    app_private_key_secret_id = optional(string, "")
    token_secret_id           = optional(string, "")
  })
  sensitive = true
}
variable "cache" {
  type = object({
    storage_name = string
    path         = optional(string, "/cache")
  })
}
variable "runtime_env" { type = string }
variable "worker" {
  type = object({
    request_interval_seconds  = optional(number, 5)
    schedule_interval_seconds = optional(number, 300)
    max_requests              = optional(number, 20)
    max_repositories          = optional(number, 5)
  })
}
variable "resources" { type = object({ cpu = number, memory = string }) }
variable "tags" { type = map(string) }
