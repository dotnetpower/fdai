variable "name" { type = string }
variable "platform" {
  type = object({
    resource_group_name          = string
    container_app_environment_id = string
    acr_login_server             = string
    acr_resource_id              = string
  })
}
variable "image" { type = string }
variable "identity" { type = object({ resource_id = string, client_id = string, principal_id = string }) }
variable "database" {
  type      = object({ dsn_secret_id = string, dsn_secret_scope = string, host = string, role = string })
  sensitive = true
}
variable "registries" { type = object({ trust_path = string, trust_pin = string, grant_path = string, grant_pin = string }) }
variable "anchors_json" {
  type      = string
  sensitive = true
}
variable "executor_anchors" {
  type = object({
    core_runtime_executor           = string
    isolated_executor               = string
    dev_operations_gateway_executor = string
    vertical_effect_executors       = set(string)
    deploy_runner                   = string
  })
}
variable "caller_auth" {
  type      = object({ issuer = string, audience = string, jwks_json = string })
  sensitive = true
}
variable "own_role_readback" { type = object({ scopes = set(string) }) }
variable "health" {
  type = object({
    port                    = number
    liveness_path           = optional(string)
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 30)
  })
}
variable "runtime_env" { type = string }
variable "scaling" { type = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }) }
variable "tags" {
  type    = map(string)
  default = {}
}
