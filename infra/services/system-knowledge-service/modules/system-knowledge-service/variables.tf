variable "name" { type = string }
variable "bot_name" { type = string }
variable "image" { type = string }
variable "source_revision" { type = string }
variable "platform" {
  type = object({
    resource_group_name          = string
    location                     = string
    container_app_environment_id = string
    acr_login_server             = string
    acr_id                       = string
    key_vault_id                 = string
    claim_storage_account_id     = string
    claim_storage_blob_endpoint  = string
  })
}
variable "teams" {
  type = object({
    transport               = string
    tenant_id               = string
    team_ids                = list(string)
    channel_ids             = list(string)
    allowed_service_urls    = optional(list(string), [])
    jwks_url                = optional(string, "")
    principal_map_secret_id = string
    outgoing_hmac_secret_id = optional(string)
  })
  sensitive = true
}
variable "claim_store" { type = object({ container_name = string }) }
variable "health" {
  type = object({
    port                    = number
    liveness_path           = string
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 60)
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
